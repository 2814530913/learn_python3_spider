#!/usr/bin/env python3
"""Organize existing Zhihu pages in a Notion data source without changing their body."""
import json
import logging
import os
import re
import time
from pathlib import Path
import requests

ROOT = Path("/opt/notion-organizer")
DS = "05c86be6-95e8-4823-b711-90e81999abac"
API = "https://api.notion.com/v1"
TOKEN = os.getenv("NOTION_TOKEN") or (ROOT / ".notion_token").read_text().strip()
S = requests.Session()
S.headers.update({"Authorization": "Bearer " + TOKEN, "Notion-Version": "2025-09-03", "Content-Type": "application/json"})
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

def api(method, path, data=None):
    for n in range(9):
        r = S.request(method, API + path, json=data, timeout=45)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(min(60, float(r.headers.get("Retry-After", 2 ** min(n, 5)))))
            continue
        r.raise_for_status()
        time.sleep(0.38)
        return r.json()
    raise RuntimeError("Notion API retries exhausted")

def text(p):
    return "".join(x.get("plain_text", "") for x in p.get(p.get("type", ""), [])) if p else ""

def rich(value):
    return [{"type": "text", "text": {"content": str(value)[:1900]}}]

RULES = [
    ("职场与教育", "学业与职业", "研究生教育", r"研究生|导师|考研|论文|毕业|文献|求职|面试"),
    ("情感与人际关系", "恋爱与婚姻", "亲密关系", r"恋爱|脱单|相亲|结婚|分手|女朋友|男朋友|追女生"),
    ("情感与人际关系", "人际关系", "社交沟通", r"社交|人际|沟通|交往|朋友"),
    ("个人成长与心理", "心理与成长", "心理认知", r"心理|焦虑|自卑|情绪|孤独|成长|人生"),
    ("计算机与互联网", "软件与网络", "数字技术", r"Linux|Python|编程|服务器|互联网|电脑|软件"),
    ("科学与工程", "工程技术", "科学知识", r"电气|电力|电网|物理|数学|工程"),
    ("历史文化与娱乐", "文化与娱乐", "文娱作品", r"历史|文学|电影|游戏|动漫|小说"),
    ("生活与健康", "健康与生活", "健康知识", r"健康|疾病|糖尿病|健身|睡眠"),
    ("经济与社会", "经济与社会", "社会观察", r"经济|房价|工资|法律|政策|政府"),
]

def summary(page_id):
    data = api("GET", "/blocks/" + page_id + "/children?page_size=100")
    parts = []
    for block in data.get("results", []):
        kind = block.get("type")
        if kind not in ("paragraph", "bulleted_list_item", "numbered_list_item"):
            continue
        s = "".join(z.get("plain_text", "") for z in block[kind].get("rich_text", [])).strip()
        if len(s) > 18 and not re.search(r"导出日期|发布日期|知乎\+\+|GitHub地址", s):
            parts.append(s)
        if sum(map(len, parts)) >= 190:
            break
    return " ".join(parts)[:240]

def organize(page):
    p = page.get("properties", {})
    raw = text(p.get("文章标题"))
    m = re.fullmatch(r"zhihu\+\+_(.*?)_(.+?)_(answer|article)_(\d+)_\d{8}_\d+", raw)
    if not m:
        return False
    title, author, kind, uid = m.groups()
    title = title.replace("_", " ")
    first, second, third = next(((a,b,c) for a,b,c,pattern in RULES if re.search(pattern, title, re.I)), ("其他与待分类", "待进一步识别", "待复核"))
    props = {"文章标题":{"title":rich(title)}, "一级分类":{"select":{"name":first}}, "二级分类":{"rich_text":rich(second)}, "三级分类":{"rich_text":rich(third)}, "知乎唯一ID":{"rich_text":rich(kind+"_"+uid)}, "知乎原文":{"url":("https://www.zhihu.com/answer/" if kind=="answer" else "https://zhuanlan.zhihu.com/p/")+uid}, "分类审核":{"select":{"name":"待复核"}}}
    if not p.get("阅读状态", {}).get("select"):
        props["阅读状态"]={"select":{"name":"未读"}}
    if not text(p.get("内容摘要")):
        sample = summary(page["id"])
        if sample:
            props["内容摘要"]={"rich_text":rich(sample)}
    api("PATCH", "/pages/"+page["id"], {"properties":props})
    return True

def main():
    api("GET", "/data_sources/"+DS)
    cursor=None; updated=skipped=failed=0
    while True:
        params={"page_size":100}
        if cursor: params["start_cursor"]=cursor
        batch=api("POST", "/data_sources/"+DS+"/query", params)
        for page in batch["results"]:
            try:
                if organize(page): updated+=1
                else: skipped+=1
            except Exception:
                failed+=1
                logging.exception("Failed for page %s", page.get("id"))
            if (updated+failed)%10==0 and (updated+failed): logging.info("更新=%d 跳过=%d 失败=%d",updated,skipped,failed)
        if not batch.get("has_more"):break
        cursor=batch.get("next_cursor")
        if not cursor:break
    logging.info("完成：更新=%d 跳过=%d 失败=%d",updated,skipped,failed)

if __name__=="__main__":
    main()
