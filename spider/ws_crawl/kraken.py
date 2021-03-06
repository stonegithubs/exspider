#! /usr/bin/python
# -*- coding:utf-8 -*-
# @zhuchen    : 2019-03-30 17:37


from __future__ import absolute_import

import ujson

from spider.ws_crawl import HoldBase, WS_TYPE_KLINE, WS_TYPE_TRADE


class kraken(HoldBase):

    def __init__(self, loop=None, http_proxy=None, ws_proxy=None, *args, **kwargs):
        super().__init__(loop=loop, http_proxy=http_proxy, ws_proxy=ws_proxy, *args, **kwargs)
        self.exchange_id = 'kraken'
        self.http_timeout = 5
        self.ws_timeout = 5
        self.http_data = {
            'headers': {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/72.0.3626.119 Safari/537.36'
            },
            'api': 'https://api.kraken.com/0/public',
            'urls': {
                'symbols': '/AssetPairs',
                'trades': '/Trades?pair={}',
                'klines': '/OHLC?pair={}&interval=1'
            },
            'limits': {
                'kline': 200,
                'trade': 200,
            }
        }
        self.ws_data = {
            'api': {
                'ws_url': 'wss://ws.kraken.com'
            }
        }
        self.coin_map = {
            'XBT': 'BTC'
        }
        self.symbols = self.get_symbols()
        self.sub_symbol_id_map = {}


    def get_symbols(self):
        api = self.http_data['api']
        path = self.http_data['urls']['symbols']
        url = f'{api}{path}'
        data = self.requests_data(url)
        if not data or not data.get('result'):
            raise BaseException(f'{self.exchange_id} get symbols error')
        symbols = {}
        symbol_data = data['result']
        for x in symbol_data:
            info = symbol_data[x]
            if 'altname' not in info or 'wsname' not in info:
                continue
            ws_data = info['wsname'].upper()
            base, quote = ws_data.split('/')
            if base in self.coin_map:
                base = self.coin_map[base]
            if quote in self.coin_map:
                quote = self.coin_map[quote]
            symbol = f'{base}{quote}'.lower()
            symbols[symbol] = ws_data
        return symbols

    async def parse_pair(self, pair):
        """
        功能: 'XBT/USD' >> 'btcusd'
        """
        pair = pair.upper()
        base, quote = pair.split('/')
        if base in self.coin_map:
            base = self.coin_map[base]
        if quote in self.coin_map:
            quote = self.coin_map[quote]
        symbol = f'{base}{quote}'.lower()
        return symbol

    async def get_ws_url(self, ws_type=None):
        """
        功能:
            生成 ws 链接
        """
        return self.ws_data['api']['ws_url']

    async def get_ping_data(self):
        return ujson.dumps({
            "event": "ping",
            "reqid": await self.now_timestamp
        })

    async def get_trade_sub_data(self, symbols):
        """
        功能:
            获取 订阅消息
            支持 同时多个订阅, 所以 复写 父类方法
        """
        pairs = [self.symbols.get(x) for x in symbols if x in self.symbols]
        return ujson.dumps(
            {
                "event": "subscribe",
                "pair": pairs,
                "subscription": {
                    "name": "trade",
                }
            }
        )

    async def get_kline_sub_data(self, symbols):
        """
        功能:
            获取 订阅消息
            支持 同时多个订阅, 所以 复写 父类方法
        """
        pairs = [self.symbols.get(x) for x in symbols if x in self.symbols]
        return ujson.dumps(
            {
                "event": "subscribe",
                "pair": pairs,
                "subscription": {
                    "name": "ohlc",
                    "interval": 1
                }
            }
        )

    async def send_the_first_sub(self, send_sub_datas, ws, ws_type=None, pending_symbols=None):
        """
        功能:
            建立ws 连接后 发送订阅消息
            首次 获取任意待启动的
            重连 只获取当前脚本的
        """
        if not self.is_send_sub_data:
            return
        send_sub_datas = [] if not send_sub_datas else send_sub_datas
        if pending_symbols:
            if ws_type == WS_TYPE_TRADE:
                send_sub_datas.append(
                    await self.get_trade_sub_data(pending_symbols)
                )
            elif ws_type == WS_TYPE_KLINE:
                send_sub_datas.append(
                    await self.get_kline_sub_data(pending_symbols)
                )
            send_sub_datas = set(send_sub_datas)
        for sub_data in send_sub_datas:
            await ws.send_str(sub_data)

    async def send_new_symbol_sub(self, pending_symbols, ws, ws_type=None):
        """
        功能:
            重连 以后 检测是否有新的订阅
            binance 这种的通过url订阅的, 只能先关闭, 再重新启动
        """
        new_send_sub_datas = []
        if ws_type == WS_TYPE_TRADE:
            new_send_sub_datas = [
                await self.get_trade_sub_data(pending_symbols)
            ] if pending_symbols else []
        elif ws_type == WS_TYPE_KLINE:
            new_send_sub_datas = [
                await self.get_kline_sub_data(pending_symbols)
            ] if pending_symbols else []
        for sub_data in new_send_sub_datas:
            await ws.send_str(sub_data)

    async def get_restful_trade_url(self, symbol):
        """
        功能:
            获取 restful 请求的url
        """
        http_symbol = self.symbols.get(symbol).replace('/', '')
        api = self.http_data['api']
        path = self.http_data['urls']['trades'].format(http_symbol)
        url = f'{api}{path}'
        return url

    async def get_restful_kline_url(self, symbol, timeframe, limit=None):
        """
        功能:
            获取 restful 请求的url
        """
        http_symbol = self.symbols.get(symbol).replace('/', '')
        api = self.http_data['api']
        path = self.http_data['urls']['klines'].format(http_symbol)
        url = f'{api}{path}'
        return url

    async def parse_restful_trade(self, data, symbol, is_save=True):
        """
        功能:
            处理 restful 返回 trade
            封装成统一格式 保存到Redis中
        返回:
            [[1551760709,"10047738192326012742563","ask",3721.94,0.0235]]
        """
        trade_list = []
        if not data or not data.get('result'):
            return trade_list
        ret_data = data['result']
        trades_data_list = ret_data[symbol.upper()] if symbol.upper() in ret_data else []
        for x in trades_data_list:
            format_trade = await self.format_trade([
                int(float(x[2])),  # 秒级时间戳
                x[2],
                x[3],
                x[0],
                x[1]
            ])
            if not format_trade:
                continue
            trade_list.append(format_trade)
        if is_save:
            await self.save_trades_to_redis(symbol, trade_list)
        else:
            return trade_list

    async def parse_trade(self, msg, ws):
        """
        功能:
            处理 ws 实时trade
        """
        try:
            data = ujson.loads(msg)
            if 'channelID' in data:
                symbol = await self.parse_pair(data['pair'])
                self.sub_symbol_id_map[data['channelID']] = symbol
                return
            if not isinstance(data, list):
                return
        except Exception as e:
            return
        tick_data_list = data[1]
        symbol = self.sub_symbol_id_map.get(data[0])
        if not symbol:
            return
        trade_list = []
        for x in tick_data_list:
            format_trade = await self.format_trade([
                int(float(x[2])),  # 秒级时间戳
                x[2],
                x[3],
                x[0],
                x[1]
            ])
            if not format_trade:
                continue
            trade_list.append(format_trade)
        await self.save_trades_to_redis(symbol, trade_list, ws)
        return

    async def parse_restful_kline(self, data):
        """
        功能:
            处理 restful 返回 kline
            统一格式 ohlcv = [tms, open, high, low, close, volume]

        """
        if not data or not data.get('result'):
            return
        ohlcv_list = []
        for x in list(data['result'].values())[0]:
            ohlcv = await self.format_kline(
                [
                    x[0], x[1], x[2], x[3], x[4], x[6]
                ]
            )
            if ohlcv:
                ohlcv_list.append(ohlcv)
        return ohlcv_list

    async def parse_kline(self, msg, ws):
        try:
            data = ujson.loads(msg)
            if 'channelID' in data:
                symbol = await self.parse_pair(data['pair'])
                self.sub_symbol_id_map[data['channelID']] = symbol
                return
            if not isinstance(data, list):
                return
        except Exception as e:
            await self.logger.error(e)
            return
        kline = data[1]
        symbol = self.sub_symbol_id_map.get(data[0])
        ohlcv = await self.format_kline([
            float(kline[0]) // 60 * 60,
            kline[2],
            kline[3],
            kline[4],
            kline[5],
            kline[7],
        ])
        await self.save_kline_to_redis(symbol, ohlcv)