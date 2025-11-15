class SmartContract:
    def __init__(self, address):
        self.address = address
        self.storage = {}
        
    def execute(self, function_name, *args):
        raise NotImplementedError("Método execute deve ser implementado")

class TransferContract(SmartContract):
    def __init__(self, address):
        super().__init__(address)
        self.storage['saldos'] = {}
    
    def execute(self, function_name, *args):
        if function_name == 'transferir':
            return self.transferir(*args)
        elif function_name == 'consultar_saldo':
            return self.consultar_saldo(*args)
        return False
    
    def transferir(self, de, para, quantia):
        saldo_de = self.storage['saldos'].get(de, 0)
        if saldo_de >= quantia:
            self.storage['saldos'][de] = saldo_de - quantia
            self.storage['saldos'][para] = self.storage['saldos'].get(para, 0) + quantia
            return True
        return False
    
    def consultar_saldo(self, endereco):
        return self.storage['saldos'].get(endereco, 0)