import requests
import time
import json

API_URL = "http://blockchain-app:5000"

def test_api():
    print("=== Testando Mini Blockchain API ===\n")
    
    # 1. Cadastro de usuários
    print("1. Cadastrando usuários...")
    users = ['alice', 'bob', 'carol']
    for user in users:
        response = requests.post(f"{API_URL}/cadastro", json={'usuario': user})
        print(f"   {user}: {response.json()}")
    
    time.sleep(1)
    
    # 2. Implantar contrato
    print("\n2. Implantando contrato...")
    response = requests.post(f"{API_URL}/implantar_contrato", 
                           json={'usuario': 'alice', 'tipo_contrato': 'TransferContract'})
    print(f"   {response.json()}")
    contract_address = response.json().get('endereco_contrato')
    
    # 3. Depositar no contrato
    print("\n3. Depositando no contrato...")
    response = requests.post(f"{API_URL}/executar_contrato", 
                           json={
                               'usuario': 'alice',
                               'endereco_contrato': contract_address,
                               'funcao': 'depositar',
                               'parametros': ['alice', 100]
                           })
    print(f"   {response.json()}")
    
    # 4. Transferir via contrato
    print("\n4. Transferindo via contrato...")
    response = requests.post(f"{API_URL}/executar_contrato", 
                           json={
                               'usuario': 'alice',
                               'endereco_contrato': contract_address,
                               'funcao': 'transferir',
                               'parametros': ['alice', 'bob', 30]
                           })
    print(f"   {response.json()}")
    
    # 5. Consultar saldos
    print("\n5. Consultando saldos no contrato...")
    for user in ['alice', 'bob']:
        response = requests.post(f"{API_URL}/consultar_saldo_contrato", 
                               json={'endereco_contrato': contract_address, 'endereco': user})
        print(f"   {user}: {response.json()}")
    
    # 6. Info da blockchain
    print("\n6. Informações da blockchain...")
    response = requests.get(f"{API_URL}/info")
    print(f"   {json.dumps(response.json(), indent=2)}")

if __name__ == '__main__':
    try:
        test_api()
    except Exception as e:
        print(f"Erro ao testar API: {e}")