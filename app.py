from flask import Flask, request, jsonify
from modelo.blockchain import Blockchain

app = Flask(__name__)
blockchain = Blockchain()

@app.route('/implantar_contrato', methods=['POST'])
def implantar_contrato():
    data = request.get_json()
    usuario = data.get('usuario')
    tipo_contrato = data.get('tipo_contrato', 'TransferContract')
    
    contract_address = blockchain.deploy_contract(tipo_contrato, usuario)
    if contract_address:
        return jsonify({
            "mensagem": f"Contrato implantado com sucesso",
            "endereco_contrato": contract_address
        }), 201
    return jsonify({"erro": "Falha ao implantar contrato"}), 400

@app.route('/executar_contrato', methods=['POST'])
def executar_contrato():
    data = request.get_json()
    usuario = data.get('usuario')
    contract_address = data.get('endereco_contrato')
    funcao = data.get('funcao')
    parametros = data.get('parametros', [])
    
    resultado, mensagem = blockchain.execute_contract(
        contract_address, funcao, usuario, *parametros
    )
    
    if resultado:
        return jsonify({"mensagem": mensagem}), 200
    return jsonify({"erro": mensagem}), 400

@app.route('/consultar_saldo_contrato', methods=['POST'])
def consultar_saldo_contrato():
    data = request.get_json()
    contract_address = data.get('endereco_contrato')
    endereco = data.get('endereco')
    
    if contract_address in blockchain.contracts:
        contrato = blockchain.contracts[contract_address]
        saldo = contrato.consultar_saldo(endereco)
        return jsonify({"saldo": saldo}), 200
    return jsonify({"erro": "Contrato não encontrado"}), 400