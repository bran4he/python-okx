"""
查询 BTC-USDT-SWAP 合约价格和 K 线数据

使用 OKX API 获取 BTC 永续合约的实时价格和最近 1 小时的 15 分钟 K 线
展示布林带指标（BOLL、UB、LB），并进行做空网格策略模拟
"""

from okx import MarketData as Market
from datetime import datetime, timezone, timedelta
import statistics

# 代理配置
PROXY = 'http://127.0.0.1:7890'

# 创建市场数据 API 实例
market_api = Market.MarketAPI(proxy=PROXY)

# BTC 永续合约交易对 ID
BTC_SWAP_ID = 'BTC-USDT-SWAP'

def get_btc_swap_price():
    """
    获取 BTC 永续合约实时价格

    Returns:
        dict: 包含 BTC 价格信息的字典
    """
    result = market_api.get_ticker(BTC_SWAP_ID)
    return result

def get_btc_swap_candles(limit=100):
    """
    获取 BTC 永续合约 15 分钟 K 线数据

    Args:
        limit: 获取的 K 线数量，默认 100 条（用于计算布林带）

    Returns:
        list: K 线数据列表
    """
    # bar='15m' 表示 15 分钟 K 线
    result = market_api.get_candlesticks(instId=BTC_SWAP_ID, bar='15m', limit=str(limit))
    return result

def calculate_bollinger_bands(closes, period=20, k=2):
    """
    计算布林带指标

    Args:
        closes: 收盘价列表
        period: 周期，默认 20
        k: 标准差倍数，默认 2

    Returns:
        list: 每个元素是 (boll, ub, lb) 元组，无数据位置为 None
    """
    boll_bands = []

    for i in range(len(closes)):
        if i < period - 1:
            # 数据不足，返回 None
            boll_bands.append((None, None, None))
        else:
            # 获取最近 period 个数据
            window = closes[i - period + 1:i + 1]
            middle_band = statistics.mean(window)
            std_dev = statistics.stdev(window)

            upper_band = middle_band + k * std_dev
            lower_band = middle_band - k * std_dev

            boll_bands.append((middle_band, upper_band, lower_band))

    return boll_bands

def simulate_short_grid(candles, boll_bands, current_price, total_usdt=1000, leverage=10):
    """
    模拟做空网格策略

    Args:
        candles: K 线数据列表
        boll_bands: 对应的布林带数据
        current_price: 当前市场价格（用于最终平仓）
        total_usdt: 投资总额
        leverage: 杠杆倍数

    Returns:
        dict: 包含模拟结果的字典
    """
    # 获取最后一根 K 线对应的布林带（使用当前 UB 和 LB）
    last_boll, ub, lb = boll_bands[-1]

    # 生成 4 个等差网格线（从 LB 到 UB）
    grid_lines = []
    grid_spacing = (ub - lb) / 4  # 等差间距
    for i in range(4):
        grid_line = lb + grid_spacing * i
        grid_lines.append(grid_line)

    # 第一次成交定在 BOLL（中轨）
    first_entry = last_boll

    print(f"\n【做空网格策略参数】")
    print(f"投资总额:     {total_usdt} USDT")
    print(f"杠杆倍数:     {leverage}x")
    print(f"LB (下轨):    {lb:.2f} USDT")
    print(f"UB (上轨):    {ub:.2f} USDT")
    print(f"BOLL (中轨):   {last_boll:.2f} USDT")
    print(f"网格间距:      {grid_spacing:.2f} USDT")
    print(f"网格线数量:    4 条")
    print(f"网格线分布:    {[f'{line:.2f}' for line in grid_lines]}")
    print(f"首次成交价:    {first_entry:.2f} USDT (BOLL 中轨)")
    print(f"当前市价:      {current_price:.2f} USDT")
    print(f"模拟时间范围:  最近 24 小时 (96 根 15 分钟 K 线)")

    # 模拟交易
    # 做空网格：价格触及上方网格线时卖出开空单，价格触及下方时买入平空单
    # 跟踪持仓和交易记录
    short_positions = []  # (entry_price, usdt_amount)
    trades = []  # (action, price, amount, pnl)
    total_pnl = 0
    buy_count = 0  # 平仓（买入）次数
    sell_count = 0  # 开仓（卖出）次数

    # 使用倒数 96 根 K 线进行模拟（最近 24 小时）
    for candle in candles[-96:]:
        high = float(candle[2])
        low = float(candle[3])
        close = float(candle[4])

        # 检查是否触及网格线（从高到低遍历，避免同时触发）
        for line in sorted(grid_lines, reverse=True):
            if high >= line and low < line:
                # 价格触及上方网格线：卖出开空单
                # 分配资金：简单平均分配
                usdt_amount = total_usdt / 4
                # 使用杠杆后，实际持仓数量 = (USDT金额 / 价格) * 杠杆倍数
                position_amount = (usdt_amount / line) * leverage

                short_positions.append({
                    'entry_price': line,
                    'usdt_amount': usdt_amount,
                    'amount': position_amount
                })
                trades.append(('sell', line, position_amount, 0))
                sell_count += 1
                break  # 只触发一次

        # 检查是否需要平仓（价格触及下方网格线时）
        for i, pos in enumerate(short_positions):
            entry_price = pos['entry_price']
            # 如果当前价格低于入场价，平仓
            if low < entry_price:
                pnl = (entry_price - close) * pos['amount']
                total_pnl += pnl
                trades.append(('buy', close, pos['amount'], pnl))
                buy_count += 1
                short_positions.pop(i)
                break  # 只平一个仓位

    # 计算当前持仓的浮动盈亏
    floating_pnl = 0
    for pos in short_positions:
        pnl = (pos['entry_price'] - current_price) * pos['amount']
        floating_pnl += pnl

    # 按当前市价平仓所有持仓
    close_all_pnl = floating_pnl
    final_pnl = total_pnl + close_all_pnl
    profit_rate = (final_pnl / total_usdt) * 100

    # 输出结果
    print(f"\n【交易记录】")
    for trade in trades:
        action, price, amount, pnl = trade
        action_str = "卖出开空单" if action == 'sell' else "买入平空单"
        pnl_str = f"{pnl:.2f} USDT" if pnl != 0 else ""
        print(f"{action_str}: 价格 {price:.2f}, 数量 {amount:.6f}, {pnl_str}")

    print(f"\n【模拟结果】")
    print(f"卖出开仓次数: {sell_count}")
    print(f"买入平仓次数: {buy_count}")
    print(f"已实现利润:   {total_pnl:.2f} USDT")
    print(f"当前持仓浮盈: {floating_pnl:.2f} USDT")
    print(f"按市价平仓利润: {close_all_pnl:.2f} USDT")
    print(f"总利润:       {final_pnl:.2f} USDT")
    print(f"利润率:       {profit_rate:.2f}%")

    return {
        'sell_count': sell_count,
        'buy_count': buy_count,
        'realized_pnl': total_pnl,
        'floating_pnl': floating_pnl,
        'close_all_pnl': close_all_pnl,
        'total_pnl': final_pnl,
        'profit_rate': profit_rate,
        'grid_lines': grid_lines,
        'first_entry': first_entry,
        'trades': trades
    }

def format_timestamp(ts_ms):
    """将毫秒时间戳转换为北京时间（UTC+8）"""
    # UTC+8 (北京时间)
    tz = timezone(timedelta(hours=8))
    return datetime.fromtimestamp(int(ts_ms) / 1000, tz=tz).strftime('%Y-%m-%d %H:%M:%S CST')


def main():
    """主函数：查询并打印 BTC 合约价格和 K 线数据"""
    print("=" * 60)
    print("OKX BTC-USDT-SWAP 永续合约")
    print("=" * 60)

    # 查询实时价格
    ticker_result = get_btc_swap_price()

    if ticker_result and ticker_result.get('code') == '0' and ticker_result.get('data'):
        ticker_data = ticker_result['data'][0]
        current_price = float(ticker_data.get('last', 0))

        print(f"\n【实时价格】")
        print(f"交易对:     {ticker_data.get('instId', 'N/A')}")
        print(f"最新价格:   {ticker_data.get('last', 'N/A')}")
        print(f"最高买价:   {ticker_data.get('bidPx', 'N/A')}")
        print(f"最低卖价:   {ticker_data.get('askPx', 'N/A')}")
        print(f"24h 最高:   {ticker_data.get('high24h', 'N/A')}")
        print(f"24h 最低:   {ticker_data.get('low24h', 'N/A')}")
        print(f"24h 成交量: {ticker_data.get('volCcy24h', 'N/A')}")
        print(f"资金费率:   {ticker_data.get('fundingRate', 'N/A')}")
    else:
        print(f"\n价格查询失败: {ticker_result}")
        return

    current_price = float(ticker_data.get('last', 0))

    # 查询 15 分钟 K 线（获取 100 条数据用于计算布林带，模拟 24 小时）
    candles_result = get_btc_swap_candles(limit=100)

    if candles_result and candles_result.get('code') == '0' and candles_result.get('data'):
        candles = candles_result['data']

        # 提取收盘价用于计算布林带
        closes = [float(candle[4]) for candle in candles]

        # 计算布林带（20周期，2倍标准差）
        boll_bands = calculate_bollinger_bands(closes, period=20, k=2)

        # 取最后 96 根 K 线（最近 24 小时）进行模拟和展示

        print(f"\n【最近 24 小时 15 分钟 K 线（含布林带）- 展示最后 10 根】")
        print(f"{'时间':<20} {'收盘':>10} {'BOLL':>10} {'UB(上轨)':>12} {'LB(下轨)':>12} {'成交量':>10}")
        print("-" * 85)

        # 展示最后 10 根 K 线（避免输出过多）
        for candle, (boll, ub, lb) in zip(reversed(candles[-10:]), reversed(boll_bands[-10:])):
            ts = format_timestamp(candle[0])
            close_price = float(candle[4])
            volume = float(candle[5])

            boll_str = f"{boll:.2f}" if boll else "N/A"
            ub_str = f"{ub:.2f}" if ub else "N/A"
            lb_str = f"{lb:.2f}" if lb else "N/A"

            print(f"{ts:<20} {close_price:>10.2f} {boll_str:>10} {ub_str:>12} {lb_str:>12} {volume:>10.2f}")

        # K 线数据返回是倒序的（最新的在前），这里按时间正序显示
        for candle, (boll, ub, lb) in zip(reversed(candles[-96:]), reversed(boll_bands[-96:])):
            ts = format_timestamp(candle[0])
            close_price = float(candle[4])
            volume = float(candle[5])

            boll_str = f"{boll:.2f}" if boll else "N/A"
            ub_str = f"{ub:.2f}" if ub else "N/A"
            lb_str = f"{lb:.2f}" if lb else "N/A"

            print(f"{ts:<20} {close_price:>10.2f} {boll_str:>10} {ub_str:>12} {lb_str:>12} {volume:>10.2f}")

        # 调用做空网格策略模拟（使用 10 倍杠杆）
        result = simulate_short_grid(candles, boll_bands, current_price, total_usdt=1000, leverage=10)
    else:
        print(f"\nK 线查询失败: {candles_result}")

    print("=" * 60)

if __name__ == '__main__':
    main()
