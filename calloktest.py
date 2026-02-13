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

def simulate_short_grid(candles, boll_bands, current_price, total_usdt=1000, leverage=10, fee_rate=0.0002):
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
    # 做空网格策略逻辑（正确理解版）：
    # 网格线 [L1, L2, L3, L4] 从低到高
    # 核心逻辑：高卖低买
    # 1. 开空（高卖）：价格上涨触及网格线 X 时（high >= X），在 X 开空单
    # 2. 平仓（低买）：价格下跌触及网格线 Y 时（low <= Y），平掉在【上一档网格线】开的空单
    #    利润 = 开仓价 - 平仓价 = 网格间距（固定利润）
    #    例如：
    #    - 价格上涨触及 L3 → 在 L3 开空单（高卖）
    #    - 价格下跌触及 L2 → 平掉 L3 的空单（低买），利润 = L3 - L2 = 网格间距
    # 3. 如果价格持续上涨不回落，空单持续持有，等待价格回落触及下方网格线平仓
    # 跟踪持仓和交易记录
    short_positions = []  # 每个元素: {'entry_price': 开仓价格, 'usdt_amount': 金额, 'amount': 数量}
    trades = []  # (action, price, amount, pnl, fee)
    total_pnl = 0
    total_fee = 0  # 累计手续费
    buy_count = 0  # 平仓（买入）次数
    sell_count = 0  # 开仓（卖出）次数
    
    # 网格线排序（从低到高）
    sorted_lines = sorted(grid_lines)
    # 记录每个网格线上是否已有持仓（做空网格：每个网格线最多一笔空单）
    line_has_position = {line: False for line in grid_lines}

    # 使用倒数 96 根 K 线进行模拟（最近 24 小时）
    for candle in candles[-96:]:
        high = float(candle[2])
        low = float(candle[3])
        close = float(candle[4])
        
        # 记录本轮K线处理前的持仓状态
        positions_before = len(short_positions)
        
        # ===== 第一步：检查平仓条件（价格下跌触及下方网格线时平仓）=====
        # 从低到高检查平仓（价格下跌时平掉上方开的空单）
        for i, line in enumerate(sorted_lines):
            # 如果价格下跌触及该网格线（low <= line）
            if low <= line:
                # 平掉在【上一档网格线】开的空单（如果有）
                if i + 1 < len(sorted_lines):
                    upper_line = sorted_lines[i + 1]
                    if line_has_position[upper_line]:
                        # 找出在上一档网格线开仓的所有持仓
                        positions_to_close = [idx for idx, pos in enumerate(short_positions) 
                                              if pos['entry_price'] == upper_line]
                        for idx in reversed(positions_to_close):
                            pos = short_positions[idx]
                            # 平仓价格 = 当前网格线价格（固定利润）
                            close_price = line
                            pnl = (pos['entry_price'] - close_price) * pos['amount']
                            close_fee = close_price * pos['amount'] * fee_rate
                            total_fee += close_fee
                            total_pnl += pnl
                            trades.append(('buy', close_price, pos['amount'], pnl, close_fee))
                            buy_count += 1
                            short_positions.pop(idx)
                        line_has_position[upper_line] = False
        
        # 检查本轮是否触发了平仓
        closed_count = positions_before - len(short_positions)
        
        # ===== 第二步：检查开仓条件（价格上涨触及网格线时开空）=====
        # 注意：
        # 1. 如果本轮K线触发了平仓（价格下跌），说明价格在下跌趋势中，不应开新仓
        # 2. 如果价格跌破了最低网格线，按照OKX文档，程序停止操作
        lowest_line = sorted_lines[0]
        if closed_count == 0 and low > lowest_line:  # 只有没有平仓且未跌破最低网格线时才开新仓
            # 从高到低遍历网格线（优先在较高价格开空）
            for line in sorted(grid_lines, reverse=True):
                # 价格上涨触及该网格线（high >= line），且该网格线没有持仓，则开空单
                if high >= line and not line_has_position[line]:
                    # 分配资金：简单平均分配
                    usdt_amount = total_usdt / 4
                    # 使用杠杆后，实际持仓数量 = (USDT金额 / 价格) * 杠杆倍数
                    position_amount = (usdt_amount / line) * leverage

                    short_positions.append({
                        'entry_price': line,
                        'usdt_amount': usdt_amount,
                        'amount': position_amount
                    })
                    # 开仓手续费 = 开仓金额 × 手续费率
                    open_fee = line * position_amount * fee_rate
                    total_fee += open_fee
                    trades.append(('sell', line, position_amount, 0, open_fee))
                    sell_count += 1
                    line_has_position[line] = True
                    break  # 一根K线只触发一次开仓

    # ===== 模拟结束后，根据当前市价处理最终持仓状态 =====
    # 获取网格区间
    lowest_line = sorted_lines[0]
    highest_line = sorted_lines[-1]
    
    # 情况1：现价低于最低网格线 → 平掉所有持仓（止损/止盈）
    if current_price < lowest_line and len(short_positions) > 0:
        for pos in short_positions[:]:  # 使用切片复制列表，避免迭代时修改
            # 按当前市价平仓
            close_price = current_price
            pnl = (pos['entry_price'] - close_price) * pos['amount']
            close_fee = close_price * pos['amount'] * fee_rate
            total_fee += close_fee
            total_pnl += pnl
            trades.append(('buy', close_price, pos['amount'], pnl, close_fee))
            buy_count += 1
        short_positions.clear()
        for line in grid_lines:
            line_has_position[line] = False

    # 计算当前持仓的浮动盈亏和加权平均成本
    floating_pnl = 0
    floating_fee = 0
    total_position_amount = 0
    total_position_value = 0  # 用于计算加权平均成本
    for pos in short_positions:
        pnl = (pos['entry_price'] - current_price) * pos['amount']
        floating_pnl += pnl
        # 按市价平仓的手续费
        floating_fee += current_price * pos['amount'] * fee_rate
        # 累计持仓数量和价值
        total_position_amount += pos['amount']
        total_position_value += pos['entry_price'] * pos['amount']
    
    # 计算加权平均成本价格
    avg_entry_price = total_position_value / total_position_amount if total_position_amount > 0 else 0

    # 按当前市价平仓所有持仓
    close_all_pnl = floating_pnl
    final_pnl = total_pnl + close_all_pnl - total_fee - floating_fee
    profit_rate = (final_pnl / total_usdt) * 100
    total_fee_all = total_fee + floating_fee
    
    # ===== 分析持仓状态 =====
    position_status = ""
    if total_position_amount == 0:
        position_status = "情况1: 现价低于最低网格线，所有持仓已平仓"
    elif current_price > highest_line:
        if total_position_amount > 0:
            position_status = f"情况2: 现价高于最高网格线，持有 {len(short_positions)} 笔空单，处于浮动亏损"
    else:
        # 现价在网格区间内
        if floating_pnl > 0:
            position_status = f"情况3: 现价在网格区间内，持有 {len(short_positions)} 笔空单，浮动盈利"
        elif floating_pnl < 0:
            position_status = f"情况3: 现价在网格区间内，持有 {len(short_positions)} 笔空单，浮动亏损"
        else:
            position_status = "情况3: 现价在网格区间内，无持仓"
    
    # 检查是否存在“市价已低于某网格线，但该网格线上一档的空单未平仓”的情况
    untriggered_positions = []
    for pos in short_positions:
        entry_price = pos['entry_price']
        # 找出开仓价格对应的下一档网格线（应该触发平仓的价格）
        entry_idx = sorted_lines.index(entry_price)
        if entry_idx > 0:
            trigger_line = sorted_lines[entry_idx - 1]  # 下一档网格线
            if current_price < trigger_line:
                untriggered_positions.append({
                    'entry_price': entry_price,
                    'trigger_line': trigger_line,
                    'current_price': current_price
                })

    # 输出结果
    print(f"\n【交易记录】")
    for trade in trades:
        action, price, amount, pnl, fee = trade
        action_str = "卖出开空单" if action == 'sell' else "买入平空单"
        pnl_str = f"盈亏: {pnl:.2f} USDT" if pnl != 0 else ""
        print(f"{action_str}: 价格 {price:.2f}, 数量 {amount:.6f}, 手续费 {fee:.2f} USDT, {pnl_str}")

    print(f"\n【模拟结果】")
    print(f"卖出开仓次数: {sell_count}")
    print(f"买入平仓次数: {buy_count}")
    print(f"已实现利润:   {total_pnl:.2f} USDT")
    print(f"累计手续费:   {total_fee:.2f} USDT")
    print(f"当前持仓数量: {total_position_amount:.6f} BTC")
    print(f"持仓成本价格: {avg_entry_price:.2f} USDT")
    print(f"当前市价价格: {current_price:.2f} USDT")
    print(f"当前持仓浮盈: {floating_pnl:.2f} USDT")
    print(f"按市价平仓利润: {close_all_pnl:.2f} USDT")
    print(f"平仓手续费:   {floating_fee:.2f} USDT")
    print(f"总手续费:     {total_fee_all:.2f} USDT")
    print(f"总利润:       {final_pnl:.2f} USDT")
    print(f"利润率:       {profit_rate:.2f}%")
    print(f"\n【持仓状态分析】")
    print(f"网格下限:     {lowest_line:.2f} USDT")
    print(f"网格上限:     {highest_line:.2f} USDT")
    print(f"当前状态:     {position_status}")
    
    # 如果有持仓，列出每笔空单的详细信息
    if len(short_positions) > 0:
        print(f"\n【持仓明细】")
        print(f"{'序号':<4} {'开仓价格':<12} {'持仓数量':<14} {'当前市价':<12} {'浮动盈亏':<12} {'盈亏率':<8}")
        print("-" * 70)
        for i, pos in enumerate(short_positions, 1):
            pos_pnl = (pos['entry_price'] - current_price) * pos['amount']
            pos_pnl_rate = (pos_pnl / (pos['entry_price'] * pos['amount'])) * 100
            print(f"{i:<4} {pos['entry_price']:<12.2f} {pos['amount']:<14.6f} {current_price:<12.2f} {pos_pnl:<12.2f} {pos_pnl_rate:>6.2f}%")
        print("-" * 70)
        print(f"{'合计':<4} {avg_entry_price:<12.2f} {total_position_amount:<14.6f} {current_price:<12.2f} {floating_pnl:<12.2f} {(floating_pnl/(avg_entry_price*total_position_amount)*100) if total_position_amount > 0 else 0:>6.2f}%")
    
    # 显示未触发平仓的异常情况
    if untriggered_positions:
        print(f"\n【异常警告】")
        print("以下空单的平仓触发价高于当前市价，但未被平仓：")
        for up in untriggered_positions:
            print(f"  - 开仓价 {up['entry_price']:.2f} 应在价格跌至 {up['trigger_line']:.2f} 时平仓，当前市价 {up['current_price']:.2f} 已低于该触发价")
        print("可能原因：最后一根K线的最低价未触及触发价，或价格快速反弹后重新开仓")

    return {
        'sell_count': sell_count,
        'buy_count': buy_count,
        'realized_pnl': total_pnl,
        'total_fee': total_fee_all,
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
