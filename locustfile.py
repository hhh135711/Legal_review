"""Locust压力测试：模拟法务团队真实流量分布。

用法: locust -f locustfile.py --host http://<服务器IP>
Web界面: http://localhost:8089  设置并发数后启动

流量模型: 70% FAQ标准问题 / 20% 重复问题(命中缓存) / 10% 复杂RAG问题
"""
import random
from locust import HttpUser, task, between

FAQ_QUERIES = [
    "竞业限制期限最长多久", "采购合同预付款比例上限", "NDA保密期限一般是几年",
    "对赌协议回购利率上限", "数据出境需要什么程序", "质保金比例和质保期要求",
]
RAG_QUERIES = [
    "创始人个人回购有什么历史风险案例",
    "对赌协议的回购利率上限是多少，以及业绩补偿有没有封顶要求",
    "供应商破产源代码拿不到怎么办",
    "员工跳槽去竞品要赔多少钱",
    "2023年试用期解除的案例是什么情况",
]
HOT_QUERY = "竞业限制补偿标准是多少"  # 固定热点问题，制造缓存命中


class LegalUser(HttpUser):
    wait_time = between(0.5, 2)

    @task(7)
    def faq_query(self):
        self.client.post("/api/query", json={"query": random.choice(FAQ_QUERIES)},
                         name="L2-FAQ链路")

    @task(2)
    def cached_query(self):
        self.client.post("/api/query", json={"query": HOT_QUERY}, name="L1-缓存链路")

    @task(1)
    def rag_query(self):
        self.client.post("/api/query", json={"query": random.choice(RAG_QUERIES)},
                         name="L3-RAG链路")

    @task(1)
    def health(self):
        self.client.get("/health", name="健康检查")
