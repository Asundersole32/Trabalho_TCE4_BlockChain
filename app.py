import json
import os
from time import time
from decimal import Decimal, getcontext
from typing import Optional
from urllib.parse import urlparse
from hashlib import sha256

import requests
from flask import (
    Flask, render_template, request,
    redirect, url_for, session, flash
)

# === Decimal / money config ===
getcontext().prec = 28  # plenty for this use case

FORGE_TRIGGER = 1

COIN_SCALE = 100  # use integer cents internally (2 decimal places)
TOTAL_COINS = 1_000_000
TOTAL_SUPPLY = TOTAL_COINS * COIN_SCALE  # 100,000,000 cents
WELCOME_COINS = 10
WELCOME_AMOUNT = WELCOME_COINS * COIN_SCALE  # 1,000 cents

SYSTEM_SENDER = "__SYSTEM__"

USERS_FILE = "users.json"  # plaintext storage of username/password


# ========== Blockchain implementation ==========

class Blockchain:
    def __init__(self):
        self.authority = None
        self.blocs = []
        self.peers = set()
        self.mempool = []

        # balances[address] = int (cents)
        self.balances = {}
        self.total_distributed = 0  # total cents ever minted

        # genesis block
        self.forge(prev_hash='genesis', curr_hash=None)

    # ---- amount helpers ----

    @staticmethod
    def _to_cents(amount) -> int:
        dec = Decimal(str(amount)).quantize(Decimal("0.01"))
        return int(dec * COIN_SCALE)

    @staticmethod
    def _format_cents(cents: int) -> str:
        dec = Decimal(cents) / COIN_SCALE
        return f"{dec:.2f}"

    # ---- block forging ----

    def forge(self, prev_hash: Optional[str], curr_hash: Optional[str]):
        applied_transactions = []

        for tx in self.mempool:
            sender = tx['sender']
            content = tx['content']
            tx_type = content.get('type', 'transfer')

            if tx_type == 'mint':
                to_addr = content['to']
                amount_cents_requested = self._to_cents(content['amount'])

                if amount_cents_requested <= 0:
                    continue

                remaining = TOTAL_SUPPLY - self.total_distributed
                if remaining <= 0:
                    continue

                amount_cents = min(amount_cents_requested, remaining)

                self.balances[to_addr] = self.balances.get(to_addr, 0) + amount_cents
                self.total_distributed += amount_cents

                applied_transactions.append({
                    'type': 'mint',
                    'to': to_addr,
                    'amount': self._format_cents(amount_cents),
                    'amount_cents': amount_cents
                })

            elif tx_type == 'transfer':
                to_addr = content['to']
                amount_cents = self._to_cents(content['amount'])

                if amount_cents <= 0:
                    continue

                sender_balance = self.balances.get(sender, 0)
                if sender_balance < amount_cents:
                    # insufficient funds; ignore
                    continue

                self.balances[sender] = sender_balance - amount_cents
                self.balances[to_addr] = self.balances.get(to_addr, 0) + amount_cents

                applied_transactions.append({
                    'type': 'transfer',
                    'from': sender,
                    'to': to_addr,
                    'amount': self._format_cents(amount_cents),
                    'amount_cents': amount_cents
                })

        bloc = {
            'previous_hash': prev_hash or self.previous_block['current_hash'],
            'current_hash': '',
            'timestamp': int(time()),
            'transactions': applied_transactions
        }

        bloc['current_hash'] = curr_hash or self.hash(bloc)
        self.blocs.append(bloc)

    def new_transaction(self, sender: str, content: dict):
        if self.authority is not None and sender != SYSTEM_SENDER:
            payload = {'sender': sender, 'content': content}
            requests.post(f'http://{self.authority}/transaction/create', json=payload)
            return

        self.mempool.append({'sender': sender, 'content': content})

        if len(self.mempool) >= FORGE_TRIGGER:
            self.forge(prev_hash=None, curr_hash=None)
            self.mempool.clear()

    def register_peer(self, address: str):
        parsed_url = urlparse(address)
        peer = parsed_url.netloc or parsed_url.path
        if peer:
            self.peers.add(peer)

    def sync(self) -> bool:
        changed = False
        for peer in self.peers:
            r = requests.get(f'http://{peer}/')
            if r.status_code != 200:
                continue
            data = r.json()
            chain = data.get('chain', [])
            if len(chain) > len(self.blocs):
                self.blocs = chain
                changed = True

        if changed:
            self._rebuild_state_from_chain()
        return changed

    def _rebuild_state_from_chain(self):
        self.balances = {}
        self.total_distributed = 0

        for block in self.blocs:
            for tx in block.get('transactions', []):
                tx_type = tx.get('type')
                if tx_type == 'mint':
                    to_addr = tx['to']
                    cents = tx.get('amount_cents')
                    if cents is None:
                        cents = self._to_cents(tx['amount'])
                    self.balances[to_addr] = self.balances.get(to_addr, 0) + cents
                    self.total_distributed += cents
                elif tx_type == 'transfer':
                    from_addr = tx['from']
                    to_addr = tx['to']
                    cents = tx.get('amount_cents')
                    if cents is None:
                        cents = self._to_cents(tx['amount'])
                    self.balances[from_addr] = self.balances.get(from_addr, 0) - cents
                    self.balances[to_addr] = self.balances.get(to_addr, 0) + cents

    @property
    def previous_block(self) -> dict:
        return self.blocs[-1]

    @staticmethod
    def hash(block: dict):
        to_hash = json.dumps(block, sort_keys=True)
        return sha256(to_hash.encode()).hexdigest()

    def set_authority(self, address: str):
        self.authority = address

    # ---- "smart contract" API ----

    def create_account(self, address: str):
        if address in self.balances:
            return  # don't mint twice

        self.balances[address] = 0

        if self.total_distributed >= TOTAL_SUPPLY:
            return

        # Enqueue a mint of 10.00 coins (or less if cap nearly reached)
        self.new_transaction(
            sender=SYSTEM_SENDER,
            content={
                "type": "mint",
                "to": address,
                "amount": self._format_cents(WELCOME_AMOUNT)
            }
        )

    def transfer(self, sender: str, to: str, amount) -> bool:
        """
        Returns True if the transfer request is accepted (enqueued),
        False if the sender doesn't have enough balance.
        """
        amount_cents = self._to_cents(amount)
        if amount_cents <= 0:
            return False

        sender_balance = self.balances.get(sender, 0)
        if sender_balance < amount_cents:
            return False

        self.new_transaction(
            sender=sender,
            content={
                "type": "transfer",
                "to": to,
                "amount": str(amount)
            }
        )
        return True

    def get_balance(self, address: str) -> str:
        cents = self.balances.get(address, 0)
        return self._format_cents(cents)

    def total_in_balances(self) -> str:
        total_cents = sum(self.balances.values())
        return self._format_cents(total_cents)


# ========== User storage helpers (plaintext passwords!) ==========

def load_users():
    if not os.path.exists(USERS_FILE):
        return {}
    with open(USERS_FILE, 'r', encoding='utf-8') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def save_users(users):
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, indent=2)


# ========== Flask app setup ==========

app = Flask(__name__)
app.secret_key = "dev-secret-key-change-me"  # for sessions (not secure!)

blockchain = Blockchain()


def current_user():
    return session.get("username")


def login_required(func):
    from functools import wraps

    @wraps(func)
    def wrapper(*args, **kwargs):
        if not current_user():
            return redirect(url_for("login"))
        return func(*args, **kwargs)

    return wrapper


# ---- Routes ----

@app.route("/")
def index():
    if current_user():
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if not username or not password:
            flash("Username and password are required.", "error")
            return redirect(url_for("register"))

        users = load_users()
        if username in users:
            flash("Username already exists.", "error")
            return redirect(url_for("register"))

        # store password in plaintext (for demo only)
        users[username] = {"password": password}
        save_users(users)

        # create blockchain account and mint 10 coins if supply available
        blockchain.create_account(username)

        flash("Account created. You can now log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        users = load_users()
        user = users.get(username)

        if not user or user.get("password") != password:
            flash("Invalid username or password.", "error")
            return redirect(url_for("login"))

        session["username"] = username
        flash("Logged in successfully.", "success")
        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("username", None)
    flash("Logged out.", "success")
    return redirect(url_for("login"))


@app.route("/dashboard", methods=["GET", "POST"])
@login_required
def dashboard():
    username = current_user()
    balance = blockchain.get_balance(username)

    if request.method == "POST":
        to_user = request.form.get("to_user", "").strip()
        amount = request.form.get("amount", "").strip()

        if not to_user or not amount:
            flash("Recipient and amount are required.", "error")
            return redirect(url_for("dashboard"))

        # make sure recipient exists in user file (simple check)
        users = load_users()
        if to_user not in users:
            flash("Recipient user does not exist.", "error")
            return redirect(url_for("dashboard"))

        try:
            # just validate it parses as Decimal with 2 decimals
            Decimal(str(amount)).quantize(Decimal("0.01"))
        except Exception:
            flash("Invalid amount format. Use e.g. 12.34", "error")
            return redirect(url_for("dashboard"))

        success = blockchain.transfer(username, to_user, amount)
        if not success:
            flash("Insufficient funds or invalid amount.", "error")
        else:
            flash(f"Sent {amount} coins to {to_user}.", "success")

        return redirect(url_for("dashboard"))

    # some extra info for fun
    total = blockchain.total_in_balances()
    return render_template(
        "dashboard.html",
        username=username,
        balance=balance,
        total_supply="{:.2f}".format(TOTAL_COINS),
        total_distributed=total
    )


# Optional debug route to see the chain as JSON
@app.route("/chain")
def chain():
    return {
        "length": len(blockchain.blocs),
        "chain": blockchain.blocs
    }


if __name__ == "__main__":
    # Run with: python app.py
    app.run(debug=True)
