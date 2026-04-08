# 模型 & 价格

下表所列模型价格以“百万 tokens”为单位。Token 是模型用来表示自然语言文本的的最小单位，可以是一个词、一个数字或一个标点符号等。我们将根据模型输入和输出的总 token 数进行计量计费。

## 模型细节

注意： `deepseek-chat` 和 `deepseek-reasoner` 对应模型版本不变，为 DeepSeek-V3.2 (128K 上下文长度)，与 APP/WEB 版不同。

<table><tbody><tr><td colspan="2">模型</td><td>deepseek-chat</td><td>deepseek-reasoner</td></tr><tr><td colspan="2">BASE URL</td><td colspan="2">https://api.deepseek.com</td></tr><tr><td colspan="2">模型版本</td><td>DeepSeek-V3.2


（非思考模式）</td><td>DeepSeek-V3.2

（思考模式）</td></tr><tr><td colspan="2">上下文长度</td><td colspan="2">128K</td></tr><tr><td colspan="2">输出长度</td><td>默认 4K，最大 8K</td><td>默认 32K，最大 64K</td></tr><tr><td rowspan="4">功能</td><td>Json Output</td><td>支持</td><td>支持</td></tr><tr><td>Tool Calls</td><td>支持</td><td>支持</td></tr><tr><td>对话前缀续写（Beta）</td><td>支持</td><td>支持</td></tr><tr><td>FIM 补全（Beta）</td><td>支持</td><td>不支持</td></tr><tr><td rowspan="3">价格</td><td>百万tokens输入（缓存命中）</td><td colspan="2">0.2元</td></tr><tr><td>百万tokens输入（缓存未命中）</td><td colspan="2">2元</td></tr><tr><td>百万tokens输出</td><td colspan="2">3元</td></tr></tbody></table>

## 扣费规则

扣减费用 = token 消耗量 × 模型单价，对应的费用将直接从充值余额或赠送余额中进行扣减。 当充值余额与赠送余额同时存在时，优先扣减赠送余额。

产品价格可能发生变动，DeepSeek 保留修改价格的权利。请您依据实际用量按需充值，定期查看此页面以获知最新价格信息。