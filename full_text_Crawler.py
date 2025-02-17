from TreadCrawler import ThreadUrlCrawler
import requests
from typing import Union
from bs4 import BeautifulSoup
from Utils.MongoClient import MongoClient
import configparser


class FullTextCrawler(ThreadUrlCrawler):
    header = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.13; rv:61.0) Gecko/20100101 Firefox/61.0",
    }
    mongo_client = MongoClient("guba", "东方精工")
    failed_proxies = {}
    proxy_fail_times_treshold = 16

    def crawl(self, url):
        """
        the href of each item have different fartherPath:
            1、https://caifuhao
            2、http://guba.eastmoney.com

        :param data_json: the json data lack full text
        :return: the data json with full text
        """
        url_map = {
            "caifuhao": "https:",
            "/new": "http://guba.eastmoney.com",
        }
        match_times = 0
        url_map_len = len(url_map)
        for k, v in url_map.items():
            match_times += 1
            if k in url:
                soup = self.get_soup_form_url(v + url)
                if soup:
                    try:
                        time = soup.find("div", {"class": "time"}).text
                    except (ValueError, AttributeError) as e:
                        time = ""
                    try:

                        if soup.find("div", {"id": "post_content"}):
                            full_text = soup.find("div", {"id": "post_content"}).text
                        else:
                            full_text = soup.find("div", {"class": "newstext"}).text
                    except (ValueError, AttributeError) as e:
                        full_text = ""
                else:
                    full_text = None
                    return False
            elif match_times == url_map_len:
                full_text = None
        if full_text:
            print(f"Successfully crawled: {url}, full text: {full_text}")
            self.mongo_client.update_one(
                {"href": url}, {"$set": {"full_text": full_text, "time": time}}
            )
            return True
        elif full_text is None:
            print(f"Failed to crawl: {url}")
            return False

    def get_soup_form_url(self, url) -> Union[BeautifulSoup, None]:
        try:
            response = requests.get(
                url, headers=self.header, timeout=10, proxies=self.proxies
            )  # 使用request获取网页
            if response.status_code != 200:
                return None
            else:
                html = response.content.decode(
                    "utf-8", "ignore"
                )  # 将网页源码转换格式为html
                soup = BeautifulSoup(
                    html, features="lxml"
                )  # 构建soup对象，"lxml"为设置的解析器
                return soup
        except Exception as e:
            return None


if __name__ == "__main__":
    # 读取配置文件
    config = configparser.ConfigParser()
    config.read("setting.ini", encoding="utf-8")
    tunnel = config.get("proxies", "tunnel")
    # 启动full_text_crawler,置于后台运行,一旦有新的url加入redis中,将会自动爬取,并存入mongodb
    full_text_crawler = FullTextCrawler()
    full_text_crawler.proxies = {
        "http": "http://%(proxy)s/" % {"proxy": tunnel},
        "https": "http://%(proxy)s/" % {"proxy": tunnel},
    }
    full_text_crawler.start()
