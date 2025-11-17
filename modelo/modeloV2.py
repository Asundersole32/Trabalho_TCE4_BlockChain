import json
import requests
from _sha256 import sha256
from time import time
from typing import Optional
from urllib.parse import urlparse
from decimal import Decimal, getcontext

# Work with 2 decimal places safely
getcontext().prec = 28  # plenty for this use case

FORGE_TRIGGER = 1  # still: forge a block for each transaction

# --- Coin / "smart contract" constants ---

COIN_SCALE = 100  # store amounts as integer "cents" (2 decimal places)

TOTAL_COINS = 1_000_000
TOTAL_SUPPLY = TOTAL_COINS * COIN_SCALE  # 100,000,000 "cents"

WELCOME_COINS = 10
WELCOME_AMOUNT = WELCOME_COINS * COIN_SCALE  # 1,000 "cents"

SYSTEM_SENDER = "_SYSTEM_"  # special sender for minting on account creation


class Blockchain:
    def _init_(self):
        self.authority = None
        self.blocs = []
        self.peers = set()
        self.mempool = []

        # balances[address] = int (cents)
        self.balances = {}
        # how many cents have ever been minted/assigned
        self.total_distributed = 0

        # genesis block
        self.forge(prev_hash='genesis', curr_hash=None)

    # ---------- Helpers for amounts ----------

    @staticmethod
    def _to_cents(amount) -> int:
        """
        Convert a number or string like "12.34" to integer cents safely,
        using Decimal to avoid floating point issues.
        """
        dec = Decimal(str(amount)).quantize(Decimal("0.01"))
        return int(dec * COIN_SCALE)

    @staticmethod
    def _format_cents(cents: int) -> str:
        """
        Convert integer cents back to a string with 2 decimals.
        """
        dec = Decimal(cents) / COIN_SCALE
        # normalize to always have 2 decimal places
        return f"{dec:.2f}"

    # ---------- Core blockchain logic ----------

    def forge(self, prev_hash: Optional[str], curr_hash: Optional[str]):
        """
        Create a new block from the current mempool, applying valid
        transactions to balances.
        """
        applied_transactions = []

        # Apply transactions in mempool in order
        for tx in self.mempool:
            sender = tx['sender']
            content = tx['content']
            tx_type = content.get('type', 'transfer')

            if tx_type == 'mint':
                # Mint 10 coins (or less if near the cap) to a new user
                to_addr = content['to']
                amount_cents_requested = self._to_cents(content['amount'])

                if amount_cents_requested <= 0:
                    continue  # ignore invalid

                remaining = TOTAL_SUPPLY - self.total_distributed
                if remaining <= 0:
                    continue  # no more coins left to mint

                amount_cents = min(amount_cents_requested, remaining)

                # Apply to state
                self.balances[to_addr] = self.balances.get(to_addr, 0) + amount_cents
                self.total_distributed += amount_cents

                applied_transactions.append({
                    'type': 'mint',
                    'to': to_addr,
                    'amount': self._format_cents(amount_cents),
                    'amount_cents': amount_cents
                })

            elif tx_type == 'transfer':
                # Standard coin transfer between users
                to_addr = content['to']
                amount_cents = self._to_cents(content['amount'])

                if amount_cents <= 0:
                    continue  # ignore non-positive transfers

                sender_balance = self.balances.get(sender, 0)
                if sender_balance < amount_cents:
                    # insufficient funds; ignore this transaction
                    continue

                # Apply to state
                self.balances[sender] = sender_balance - amount_cents
                self.balances[to_addr] = self.balances.get(to_addr, 0) + amount_cents

                applied_transactions.append({
                    'type': 'transfer',
                    'from': sender,
                    'to': to_addr,
                    'amount': self._format_cents(amount_cents),
                    'amount_cents': amount_cents
                })

            else:
                # Unknown transaction type: ignore
                continue

        bloc = {
            'previous_hash': prev_hash or self.previous_block['current_hash'],
            'current_hash': '',
            'timestamp': int(time()),
            'transactions': applied_transactions
        }

        bloc['current_hash'] = curr_hash or self.hash(bloc)

        self.blocs.append(bloc)

    def new_transaction(self, sender: str, content: dict):
        """
        Add a transaction to the mempool.
        For authority setups, forward to the authority node.
        Otherwise, enqueue locally and forge a block when FORGE_TRIGGER is reached.

        Expected content formats (examples):

        Mint on account creation (internal use):
            {
                "type": "mint",
                "to": "user_id",
                "amount": "10.00"
            }

        Transfer between users:
            {
                "type": "transfer",
                "to": "receiver_id",
                "amount": "12.34"
            }
        """
        if self.authority is not None and sender != SYSTEM_SENDER:
            # Forward to authority (simple demo; authority must know how to interpret this)
            payload = {
                'sender': sender,
                'content': content
            }
            requests.post(
                f'http://{self.authority}/transaction/create',
                json=payload
            )
            return

        # Local mempool
        self.mempool.append({
            'sender': sender,
            'content': content
        })

        if len(self.mempool) >= FORGE_TRIGGER:
            self.forge(prev_hash=None, curr_hash=None)
            self.mempool.clear()

    def register(self, address: str):
        """
        Register a peer node. (Networking / sync only, not a "user account".)
        """
        parsed_url = urlparse(address)

        # Slightly safer: use netloc if present, otherwise path
        peer = parsed_url.netloc or parsed_url.path
        if peer:
            self.peers.add(peer)

    def sync(self) -> bool:
        """
        Pull chains from peers and adopt the longest one.
        Then rebuild balances and total_distributed from the chain.
        """
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
        """
        Recalculate balances and total_distributed by replaying
        all transactions in the chain from scratch.
        """
        self.balances = {}
        self.total_distributed = 0

        # Skip genesis block's transactions if any
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
        # sort_keys=True for stable hashing
        to_hash = json.dumps(block, sort_keys=True)
        return sha256(to_hash.encode()).hexdigest()

    def set_authority(self, address: str):
        self.authority = address

    # ---------- "Smart contract" API ----------

    def create_account(self, address: str):
        """
        Create a new user/node account. If there are still coins available
        (total_distributed < TOTAL_SUPPLY), this will enqueue a MINT
        transaction of 10.00 coins to this address.

        Because FORGE_TRIGGER = 1, this will immediately forge a block
        and update balances.
        """
        if address in self.balances:
            # account already exists; don't mint again
            return

        self.balances[address] = 0

        if self.total_distributed >= TOTAL_SUPPLY:
            # No welcome coins left
            return

        # Enqueue a mint transaction for 10 coins.
        # forge() will clamp to remaining supply so we never exceed 1,000,000.00
        self.new_transaction(
            sender=SYSTEM_SENDER,
            content={
                "type": "mint",
                "to": address,
                "amount": self._format_cents(WELCOME_AMOUNT)
            }
        )

    def transfer(self, sender: str, to: str, amount):
        """
        Convenience wrapper to create a transfer transaction.
        'amount' can be '12.34', 12.34 (will be stringified),
        or a Decimal, etc.
        """
        # We don't change balances here; forge() does that.
        self.new_transaction(
            sender=sender,
            content={
                "type": "transfer",
                "to": to,
                "amount": str(amount)
            }
        )

    def get_balance(self, address: str) -> str:
        """
        Get a user's balance as a string with 2 decimals.
        """
        cents = self.balances.get(address, 0)
        return self._format_cents(cents)

    def total_in_balances(self) -> str:
        """
        Sum of all user balances, mainly for checking the invariant.
        """
        total_cents = sum(self.balances.values())
        return self._format_cents(total_cents)