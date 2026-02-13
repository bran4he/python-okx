"""
OKX 做空网格策略 Web 服务器

提供 API 接口，让前端 HTML 页面获取实时行情数据
"""

from flask import Flask, jsonify, render_template_string
from flask_cors import CORS
from okx import MarketData as Market
from datetime import datetime, timezone, timedelta
import statistics

app = Flask(__name__)
CORS(app)

# 代理配置
PROXY = 'http://127.0.0.1:7890'
BTC_SWAP_ID = 'BTC-USDT-SWAP'


def get_market_data():
    """获取市场数据"""
    market_api = Market.MarketAPI(proxy=PROXY)

    # 获取实时价格
    ticker_result = market_api.get_ticker(BTC_SWAP_ID)

    # 获取 K 线数据（获取 100 条，约 25 小时数据）
    candles_result = market_api.get_candlesticks(
        instId=BTC_SWAP_ID,
        bar='15m',
        limit='100'
    )

    return {
        'ticker': ticker_result,
        'candles': candles_result
    }


def calculate_bollinger_bands(closes, period=20, k=2):
    """计算布林带"""
    boll_bands = []
    for i in range(len(closes)):
        if i < period - 1:
            boll_bands.append((None, None, None))
            continue

        window = closes[i - period + 1:i + 1]
        middle_band = statistics.mean(window)
        std_dev = statistics.stdev(window)

        upper_band = middle_band + k * std_dev
        lower_band = middle_band - k * std_dev

        boll_bands.append((middle_band, upper_band, lower_band))

    return boll_bands


@app.route('/')
def index():
    """返回前端 HTML 页面"""
    return render_template_string(open('calloktest.html', encoding='utf-8').read())


@app.route('/api/market-data')
def api_market_data():
    """API: 获取市场数据"""
    try:
        data = get_market_data()

        # 提取实时价格
        if data['ticker'].get('code') == '0' and data['ticker'].get('data'):
            ticker_data = data['ticker']['data'][0]
            current_price = float(ticker_data.get('last', 0))
        else:
            return jsonify({
                'error': 'Failed to fetch ticker data',
                'details': data['ticker']
            }), 500

        # 提取 K 线数据
        if data['candles'].get('code') == '0' and data['candles'].get('data'):
            candles = data['candles']['data']
        else:
            return jsonify({
                'error': 'Failed to fetch candles data',
                'details': data['candles']
            }), 500

        # 处理 K 线数据
        processed_candles = []
        for candle in candles:
            processed_candles.append({
                'time': datetime.fromtimestamp(int(candle[0]) / 1000, tz=timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S'),
                'open': float(candle[1]),
                'high': float(candle[2]),
                'low': float(candle[3]),
                'close': float(candle[4]),
                'volume': float(candle[5])
            })

        # 计算布林带
        closes = [c['close'] for c in processed_candles]
        boll_bands = calculate_bollinger_bands(closes)

        # 使用最后一根 K 线的布林带作为基准
        last_boll = boll_bands[-1]
        lb = last_boll[2]
        ub = last_boll[1]
        boll = last_boll[0]

        return jsonify({
            'success': True,
            'data': {
                'ticker': {
                    'instId': ticker_data.get('instId'),
                    'last': current_price,
                    'bidPx': float(ticker_data.get('bidPx', 0)),
                    'askPx': float(ticker_data.get('askPx', 0)),
                    'high24h': float(ticker_data.get('high24h', 0)),
                    'low24h': float(ticker_data.get('low24h', 0)),
                    'volCcy24h': float(ticker_data.get('volCcy24h', 0)),
                    'timestamp': datetime.now(tz=timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')
                },
                'candles': processed_candles,
                'bollinger': {
                    'period': 20,
                    'k': 2,
                    'lb': lb,
                    'ub': ub,
                    'boll': boll
                }
            }
        })


@app.route('/api/proxy-okx')
def api_proxy_okx():
    """API: 作为代理转发 OKX 请求（解决 CORS 问题）"""
    import requests
    import json
    from flask import request

    # 获取请求参数
    endpoint = request.args.get('endpoint', '')
    method = request.args.get('method', 'GET').upper()
    params = request.args.to_dict()
    params.pop('endpoint', None)
    params.pop('method', None)

    # 构建 OKX API URL
    api_url = 'https://www.okx.com' + endpoint

    try:
        # 发送请求
        proxies = {
            'http': PROXY,
            'https': PROXY
        }

        if method == 'GET':
            response = requests.get(api_url, params=params, proxies=proxies, timeout=10)
        elif method == 'POST':
            response = requests.post(api_url, json=params, proxies=proxies, timeout=10)
        else:
            return jsonify({'error': 'Unsupported method'}), 400

        return jsonify(response.json())

    except requests.exceptions.Timeout:
        return jsonify({'error': 'Request timeout'}), 504
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/health')
def health():
    """健康检查"""
    return jsonify({'status': 'ok', 'service': 'okx-grid-simulator'})


if __name__ == '__main__':
    print("=" * 60)
    print("OKX 做空网格策略 Web 服务器")
    print("=" * 60)
    print("\n启动服务器...")
    print("访问地址: http://localhost:5000")
    print("API 接口: http://localhost:5000/api/market-data")
    print("\n按 Ctrl+C 停止服务器")
    print("=" * 60)

    app.run(host='0.0.0.0', port=5000, debug=True)
