from __future__ import barry_as_FLUFL
from urllib import response
import requests
import json
from bs4 import BeautifulSoup
import click
import warnings
import yaml
from collections import defaultdict
import time
import os
from multiprocessing import Process
from apscheduler.schedulers.blocking import BlockingScheduler
import deepl
import random

warnings.filterwarnings('ignore')

config = yaml.safe_load(open('default.yaml'))

class Paper(dict):
    def __hash__(self):
        return hash(tuple(sorted(self.items())))

class DeeplTranslator():
    def __init__(self) -> None:
        self.url = 'https://www2.deepl.com/jsonrpc?method=LMT_handle_jobs'
        self.cookies = {}
        self.headers = {
            'sec-ch-ua':'" Not;A Brand";v="99", "Google Chrome";v="91", "Chromium";v="91"',
            'Accept':'application/json, text/plain, */*',
            'sec-ch-ua-mobile':'?0',
            'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Content-Type':'application/json;charset=UTF-8',
            'Sec-Fetch-Site':'same-origin',
            'Sec-Fetch-Mode':'cors',
            'Sec-Fetch-Dest':'empty'
        }

    def translate_text(self, text_list, target_lang):
        translations = []
        for text in text_list:
            sentences = text.split('.')
            sentences_before = [""] + sentences[:-1]
            sentences_after = sentences[1:] + [""]
            jobs = []
            for sentence_before, sentence, sentence_after in zip(sentences_before, sentences, sentences_after):
                job = { "kind":"default",
                        "sentences":[{"text":sentence,"id":0,"prefix":""}],
                        "raw_en_context_before":[sentence_before],
                        "raw_en_context_after":[sentence_after],
                        "preferred_num_beams":1}
                jobs.append(job)
            data = {"jsonrpc":"2.0",
                    "method": "LMT_handle_jobs",
                    "params":{
                        "jobs":jobs,
                        "lang":{
                            "preference":{"weight":{},"default":"default"},
                            "source_lang_computed":"EN",
                            "target_lang":"ZH"},
                        "priority":1,
                        "commonJobParams":{"browserType":1,"formality":None},
                        "timestamp":1651305008478
                        },
                    "id":30660005}
            response = requests.post(self.url, json=data, cookies=self.cookies, proxies=config['PROXY'], headers=self.headers).json()
            print(response)
            if "error" in response:
                break
            result = ""
            for translation in response['result']['translations']:
                result += translation['beams'][0]['sentences']['text']
            translations.append(result)
        return translations

def get_deepl():
    return DeeplTranslator()
    # auth_key = random.choice(config["DEEPL_KEY"])
    # translator = deepl.Translator(auth_key, proxy=config['PROXY'])
    # return translator

def get_papers(url):
    responce = requests.get(url, proxies=config['PROXY'])
    soup = BeautifulSoup(responce.text, 'lxml')

    all_papers = []
    content = soup.body.find("div", {'id': 'content'})
    dt_list = content.dl.find_all("dt")
    dd_list = content.dl.find_all("dd")
    arxiv_base = "https://arxiv.org/abs/"
    for i in range(len(dt_list)):
        paper = Paper()
        paper_number = dt_list[i].text.strip().split(" ")[2].split(":")[-1]
        paper['main_page'] = arxiv_base + paper_number
        paper['id'] = paper_number
        paper['pdf'] = arxiv_base.replace('abs', 'pdf') + paper_number

        paper['title'] = dd_list[i].find("div", {"class": "list-title mathjax"}).text.replace("Title: ", "").strip()
        paper['authors'] = dd_list[i].find("div", {"class": "list-authors"}).text.replace("Authors:", "").replace("\n", "").strip()
        paper['comments'] = ''
        comments_ele = dd_list[i].find("div", {"class": "list-comments mathjax"})
        if comments_ele:
            paper['comments'] = comments_ele.text.replace("Comments:", "").replace("\n", "").strip()
        paper['subjects'] = dd_list[i].find("div", {"class": "list-subjects"}).text.replace("Subjects: ", "").strip()
        paper['abstract'] = dd_list[i].find("p", {"class": "mathjax"}).text.replace("\n", " ").strip()
        
        all_papers.append(paper)

    return all_papers

def keywords_match(papers, kewwords):
    matched_ids = set()
    matched_papers = set()
    keyword_papers = defaultdict(list)
    for keyword in kewwords:
        for paper in papers:
            if keyword.lower() in (paper['abstract'] + paper['title']).lower():
                keyword_papers[keyword].append(paper)
                matched_ids.add(paper['id'])
                matched_papers.add(paper)
    abstract_list = []
    for matched_paper in matched_papers:
        abstract_list.append(matched_paper['abstract'])
    translator = get_deepl()
    translations = translator.translate_text(abstract_list, target_lang="EN-US")
    for paper, translation in zip(matched_papers, translations):
        paper['translation'] = translation

    return keyword_papers, matched_ids

def add_papers(papers):
    date = time.strftime("%Y%m%d", time.localtime())
    markdown = ''
    for i, paper in enumerate(papers):
        # markdown += f"### [钉子] **[{paper['title']}](https://www.arxiv-vanity.com/papers/{paper['id']})**\n\n"
        markdown += f"### [钉子] **[{paper['title']}]({config['EXTERNAL_URL']}/papers/{date}/{paper['id']}.html)**\n\n"
        markdown += f"- **Authors:** *{paper['authors']}*\n"
        markdown += f"- **Link:** [{paper['id']}]({paper['main_page']})\n"
        if paper['comments'] != '':
            markdown += f"- **Comments:** {paper['comments']}\n"
        markdown += f"- **Abstract[文档]:** {paper['abstract']}\n"
        if "translation" in paper:
            markdown += f"- **摘要[文档]:** {paper['translation']}\n"
        markdown += "\n\n"
    return markdown

def parse_json_to_markdown(keyword_papers):
    markdown = ""
    for kewword, papers in keyword_papers.items():
        markdown += f"# [时间] **{kewword}**\n\n"
        markdown += add_papers(papers)

    return markdown

def send_dingtalk(token, title, content):
    data = f'{{"msgtype":"markdown","markdown": {{"title":"{title}","text": "{content}"}}}}'
    requests.post(url='https://oapi.dingtalk.com/robot/send?access_token='+ token, headers={'Content-Type': 'application/json'}, data=data.encode('utf8'), proxies=config['PROXY'])

def download_paper(id):
    response = requests.get("https://www.arxiv-vanity.com/convert/?query="+id, proxies=config['PROXY'])
    count = 0
    while True:
        time.sleep(5)
        response = requests.get(f"https://www.arxiv-vanity.com/papers/{id}/render-state/", proxies=config['PROXY'])
        print(response.status_code)
        if response.status_code == 200 and count < 60:
            print(response.json())
            if response.json()['state'] != 'running':
                break
        else:
            break
        count += 1
    date = time.strftime("%Y%m%d", time.localtime())
    if not os.path.exists(f"papers/{date}"):
        os.makedirs(f"papers/{date}")
    response = requests.get(f"https://www.arxiv-vanity.com/papers/{id}/", proxies=config['PROXY'])
    with open(f"papers/{date}/{id}.html", 'w') as f:
        f.write(response.text.replace('href="/', 'href="https://www.arxiv-vanity.com/'))

def request_arxiv_vanity(paper_ids):
    process_list = []
    for paper_id in paper_ids:
        p = Process(target=download_paper,args=(paper_id,))
        p.start()
        process_list.append(p)
    for p in process_list:
        p.join()

def main():
    selected_paper_ids = set()
    for domain, kewwords in config['DOMAIN_KEYWORDS'].items():
        papers = get_papers(config['ARXIV_NEW_URL'].format(domain))
        keyword_papers, matched_ids = keywords_match(papers, kewwords)
        send_dingtalk(config['DINGTALK_TOKEN'], domain, parse_json_to_markdown(keyword_papers))
        selected_paper_ids = selected_paper_ids | matched_ids
    # print(selected_paper_ids)
    # all_matched_papers = ["2204.12835", "2204.12820", "2204.12811"]
    request_arxiv_vanity(selected_paper_ids)

if __name__ == "__main__":
    main()

    sched = BlockingScheduler()
    sched.add_job(main, 'cron', hour=9, minute=30)
    # sched.add_job(main, 'cron', day_of_week='mon-fri', hour=10, minute=30)
    # sched.add_job(main, 'interval', minutes = 10)
    sched.start()