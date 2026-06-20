from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import urllib.parse

app = Flask(__name__)
CORS(app)

@app.route('/api/fetch_nse', methods=['GET'])
def fetch_nse():
    symbol = request.args.get('symbol')
    from_date = request.args.get('from')
    to_date = request.args.get('to')
    
    if not symbol or not from_date or not to_date:
        return jsonify({"error": "Missing parameters"}), 400

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br'
    }
    
    session = requests.Session()
    session.headers.update(headers)
    
    try:
        session.get("https://www.nseindia.com", timeout=10)
        encoded_symbol = urllib.parse.quote(symbol)
        url = f"https://www.nseindia.com/api/historical/indicesHistory?indexType={encoded_symbol}&from={from_date}&to={to_date}"
        
        response = session.get(url, timeout=10)
        
        if response.status_code == 200:
            return jsonify(response.json())
        else:
            return jsonify({"error": f"NSE returned HTTP {response.status_code}"}), int(response.status_code)
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
