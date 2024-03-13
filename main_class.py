# -*- coding: utf-8 -*-
# @Time    : 2023/2/11 21:27
# @Author  : Euclid-Jie
# @File    : main_class.py
import os
import sys
import time
import pandas as pd
import pymongo
import requests
from bs4 import BeautifulSoup
from tqdm import tqdm
import logging
from retrying import retry
from test_proxy_pool import get_proxy, delete_proxy, get_proxies_count


class guba_comments:
    """
    this class is designed for get hot comments for guba, have two method which can be set at def get_data()
    1、all: https://guba.eastmoney.com/list,600519_1.html, secCode: 600519, page: 1
    2、hot: https://guba.eastmoney.com/list,600519,99_1.html secCode: 600519, page: 1

    because to the ip control, this need to set proxies pools
    by using proxies https://www.kuaidaili.com/usercenter/overview/, can solve this problem

    Program characteristics:
        1、default write data to mongoDB, by init "MogoDB=False", can switch to write data to csv file
        2、Use retry mechanism, once rise error, the program will restart at the least page and num (each page has 80 num)

    """

    def __init__(
        self,
        secCode,
        pages_end,
        pages_start=1,
        num_start=0,
        MongoDB=True,
        collectionName=None,
    ):
        # init
        self.collectionName = collectionName
        self.num_start = num_start
        self.secCode = secCode
        self.pages_end = pages_end
        self.pages_start = pages_start

        # default setting
        self.header = None
        self.SaveFolderPath = os.getcwd()
        if self.collectionName is None:
            self.collectionName = self.secCode
        self.FilePath = secCode + ".csv"
        self.DBName = "guba"

        # choose one save method, default MongoDB
        # 1、csv
        # 2、MongoDB
        if MongoDB:
            self.col = self.MongoClient()
        else:
            self.col = None

        # log setting
        log_format = "%(levelname)s %(asctime)s %(filename)s %(lineno)d %(message)s"
        logging.basicConfig(filename="test.log", format=log_format, level=logging.INFO)

    @staticmethod
    def clear_str(str_raw):
        for pat in ["\n", " ", " ", "\r", "\xa0", "\n\r\n"]:
            str_raw.strip(pat).replace(pat, "")
        return str_raw

    @retry(stop_max_attempt_number=5)  # 最多尝试5次
    def get_soup_form_url(self, url: str, use_proxy=True) -> BeautifulSoup:
        """
        get the html content used by requests.get
        :param url:
        :return: BeautifulSoup
        """
        if use_proxy:
            proxy = get_proxy().get("proxy")
            proxies = {
                "http": f"http://{proxy}",
                "https": f"http://{proxy}",
            }
            try:
                response = requests.get(
                    url, headers=self.header, timeout=10, proxies=proxies
                )  # 使用request获取网页
                if response.status_code != 200:
                    delete_proxy(proxy)
                    raise ValueError("response.status_code != 200")
                else:
                    html = response.content.decode(
                        "utf-8", "ignore"
                    )  # 将网页源码转换格式为html
                    soup = BeautifulSoup(
                        html, features="lxml"
                    )  # 构建soup对象，"lxml"为设置的解析器
                    return soup
            except Exception:
                delete_proxy(proxy)
                raise ValueError("get_soup_form_url getting fail")
        else:
            response = requests.get(url, headers=self.header, timeout=10)
            if response.status_code != 200:
                raise ValueError("response.status_code != 200")
            else:
                html = response.content.decode("utf-8", "ignore")
                soup = BeautifulSoup(html, features="lxml")
                return soup

    def get_full_text(self, data_json):
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
            if k in data_json["href"]:
                url = v + data_json["href"]
                soup = self.get_soup_form_url(url, use_proxy=True)
                try:
                    data_json["time"] = soup.find("div", {"class": "time"}).text
                    if soup.find("div", {"id": "post_content"}):
                        data_json["full_text"] = soup.find(
                            "div", {"id": "post_content"}
                        ).text
                    else:
                        data_json["full_text"] = soup.find(
                            "div", {"class": "newstext"}
                        ).text
                    data_json["full_text"] = self.clear_str(data_json["full_text"])
                except (ValueError, AttributeError) as e:
                    logging.info(
                        "{} get null full content, {}".format(data_json["href"], e)
                    )
            elif match_times == url_map_len:
                logging.info("{} is not define in url_map".format(data_json["href"]))
        return data_json

    def save_data(self, data_df):
        """
        轮子函数，用于存储数据，可实现对已存在文件的追加写入
        :param data_df: 目标数据
        :return:
        """
        # concat the folderPath and dataPath
        FileFullPath = os.path.join(self.SaveFolderPath, self.FilePath)
        if os.path.isfile(FileFullPath):
            data_df.to_csv(
                self.FilePath, mode="a", header=False, index=False, encoding="utf_8_sig"
            )
        else:
            data_df.to_csv(
                self.FilePath, mode="w", header=True, index=False, encoding="utf_8_sig"
            )

    def get_data_json(self, item):
        """
        get the special keys from item, in this the project,
        the keys con be "阅读"、"评论"、……

        by use the get_full_text, the return json data will contain full_text
        :param item:
        :return: json data contains full_text
        """

        tds = item.find_all("td")
        data_json = {
            "阅读": tds[0].text,
            "评论": tds[1].text,
            "标题": tds[2].a.text,
            "href": tds[2].a["href"],
            "作者": tds[3].a.text,
            "最后更新": tds[4].text,
        }

        return self.get_full_text(data_json)

    def get_data(self, page):
        """
        process to deal the single page's data
        :param page: the page needed to be processed
        :return:
        """
        # Url = "http://guba.eastmoney.com/list,{},99_{}.html".format(self.secCode, page)
        Url = "http://guba.eastmoney.com/list,{},f_{}.html".format(self.secCode, page)
        soup = self.get_soup_form_url(Url)
        data_list = soup.find_all("tr", "listitem")
        error_num = 0
        if self.col is not None:
            for item in data_list[self.num_start :]:
                try:
                    data_json = self.get_data_json(item)
                    self.col.insert_one(data_json)
                    self.t.set_postfix(
                        {
                            "状态": "已写num:{}".format(self.num_start),
                            "proxies counts": get_proxies_count(),
                        }
                    )  # 进度条右边显示信息
                    error_num = 0
                except ValueError as e:
                    logging.error("item get_data getting fail")
                    error_num += 1
                    if error_num >= 5:
                        sys.exit()
                finally:
                    self.num_start += 1

        elif self.FilePath:
            for item in data_list[self.num_start :]:
                try:
                    data_json = self.get_data_json(item)
                    self.save_data(pd.DataFrame(data_json, index=[0]))
                    self.t.set_postfix(
                        {
                            "状态": "已写入page:{} num:{}".format(page, self.num_start),
                            "proxies counts": get_proxies_count(),
                        }
                    )  # 进度条右边显示信息
                    error_num = 0
                except ValueError as e:
                    logging.error("item get_data getting fail")
                    error_num += 1
                    if error_num >= 5:
                        sys.exit()
                finally:
                    self.num_start += 1

        else:
            raise ValueError("please set least one method to save data")

    def MongoClient(self):
        # 连接数据库
        myclient = pymongo.MongoClient("mongodb://localhost:27017/")
        mydb = myclient[self.DBName]  # 数据库名称
        mycol = mydb[self.collectionName]  # 集合（表）
        return mycol

    def main(self):
        with tqdm(range(self.pages_start, self.pages_end)) as self.t:
            for page in self.t:
                get_proxies_count()
                self.t.set_description("page:{}".format(page))  # 进度条左边显示信息
                self.t.set_postfix({"proxies counts": get_proxies_count()})
                self.get_data(page)
                time.sleep(5)
                self.num_start = 0
                self.pages_start += 1


if __name__ == "__main__":
    # init
    demo = guba_comments(
        "002611",
        pages_start=0,
        pages_end=100,
        num_start=0,
        MongoDB=True,
        collectionName="东方精工",
    )

    # setting
    header = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.13; rv:61.0) Gecko/20100101 Firefox/61.0",
    }
    demo.header = header

    # run and get data
    demo.main()
