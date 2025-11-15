import time
import hashlib

class Block:
    def __init__(self, index, transactions, contract_transactions, previous_hash):
        self.index = index
        self.timestamp = time.time()
        self.transactions = transactions  # Transações normais
        self.contract_transactions = contract_transactions  # Transações de contrato
        self.previous_hash = previous_hash
        self.nonce = 0
        self.hash = self.calculate_hash()

    def calculate_hash(self):
        block_data = (str(self.index) + str(self.timestamp) + 
                     str(self.transactions) + str(self.contract_transactions) + 
                     str(self.previous_hash) + str(self.nonce))
        return hashlib.sha256(block_data.encode()).hexdigest()