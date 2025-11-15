from block import Block
from smartContract import SmartContract, TransferContract

class Blockchain:
    def __init__(self):
        self.chain = [self.create_genesis_block()]
        self.pending_transactions = []
        self.mining_reward = 10
        self.total_supply = 1000000
        self.user_balances = {'root': self.total_supply}
        self.contracts = {}  # Armazena contratos implantados
        self.contract_address_counter = 1
    
    def create_genesis_block(self):
        return Block(0, ["Genesis Block"], "0")
    
    def deploy_contract(self, contract_code, from_address):
        """Implanta um novo contrato na blockchain"""
        if self.user_balances.get(from_address, 0) < 1:  # Custo para implantar contrato
            return None
        
        contract_address = f"contract_{self.contract_address_counter}"
        self.contract_address_counter += 1
        
        # Criar instância do contrato
        if "TransferContract" in contract_code:
            contract = TransferContract(contract_address)
        else:
            contract = SmartContract(contract_address)
        
        self.contracts[contract_address] = contract
        self.user_balances[from_address] -= 1  # Custo de implantação
        
        return contract_address
    
    def execute_contract(self, contract_address, function_name, from_address, *args):
        """Executa uma função de um contrato"""
        if contract_address not in self.contracts:
            return False, "Contrato não encontrado"
        
        contract = self.contracts[contract_address]
        result = contract.execute(function_name, from_address, *args)
        return result, "Executado com sucesso"