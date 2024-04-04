import logging
import os
import re
import sys
from hashlib import md5  # 导入md5模块，用于生成哈希值
from pathlib import Path  # 导入Path模块，用于处理文件路径
from time import time  # 导入time模块，用于生成当前时间戳
from typing import Any, List  # 导入Any和List模块，用于类型提示

from common import LINE_RE  # 从common模块中导入LINE_RE变量
from manager import CacheManager, RequestManager  # 从manager模块中导入CacheManager和RequestManager类
from parsers import ContentParser, HTMLParser, Parser, WordParser  # 从parsers模块中导入ContentParser、HTMLParser、Parser和WordParser类

# 创建一个名为"Law"的日志记录器
logger = logging.getLogger("Law")
# 设置日志记录器的级别为DEBUG
logger.setLevel(logging.DEBUG)

# 创建一个格式化器，用于设置日志记录的格式
formatter = logging.Formatter("%(asctime)s:%(levelname)s:%(message)s")

# 创建一个流处理器，用于将日志信息输出到控制台
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)

# 将流处理器添加到日志记录器
logger.addHandler(console_handler)


def find(f, arr: List[Any]) -> Any:
    '''查找满足f条件的元素。
    如果存在满足条件的元素，返回该元素；否则抛出异常。'''
    for item in arr:
        if f(item):
            return item
    raise Exception("not found")


def isStartLine(line: str):
    # 遍历LINE_RE中的正则表达式
    for reg in LINE_RE:
        # 如果line与正则表达式匹配
        if re.match(reg, line):
            # 返回True
            return True
    # 如果没有任何正则表达式匹配，返回False
    return False


class LawParser(object):
    def __init__(self) -> None:
        # 初始化RequestManager实例
        self.request = RequestManager()
        # 初始化special title为None
        self.spec_title = None
        # 初始化parser列表，包含HTMLParser和WordParser
        self.parser = [
            HTMLParser(),
            WordParser(),
        ]
        # 初始化ContentParser实例
        self.content_parser = ContentParser()
        # 初始化CacheManager实例
        self.cache = CacheManager()
        # 初始化category列表
        self.categories = []

    def __reorder_files(self, files):
        # 过滤出类型符合的文件
        files = list(
            filter(
                lambda x: x["type"] in self.parser,
                files,
            )
        )

        # 如果文件为空，则返回空列表
        if len(files) == 0:
            return []

        # 如果文件数量大于1，则按照 parser 的位置排序， 优先使用级别
        if len(files) > 1:
            files = sorted(files, key=lambda x: self.parser.index(x["type"]))

        # 返回排序后的文件列表
        return files

    def is_bypassed_law(self, item) -> bool:
    # 替换标题中包含的“中华人民共和国”
    title = item["title"].replace("中华人民共和国", "")
    # 如果自定义标题中包含此标题，则返回False
    if self.spec_title and title in self.spec_title:
        return False
    # 如果标题中包含“的(决定|复函|批复|答复|批复)$”，则返回True
    if re.search(r"的(决定|复函|批复|答复|批复)$", title):
        return True
    # 其他情况下返回False
    return False

    def parse_law(self, item):
        # 获取法律详情
        detail = self.request.get_law_detail(item["id"])
        # 获取法律详情结果
        result = detail["result"]
        # 获取法律标题
        title = result["title"]
        # 对文件进行排序
        files = self.__reorder_files(result["body"])
        # 打印日志
        logger.debug(f"parsing {title}")
        # 如果文件为0，则返回
        if len(files) == 0:
            return

        for target_file in files:
            # 查找匹配的解析器
            parser: Parser = find(lambda x: x == target_file["type"], self.parser)

            # 调用解析器进行解析
            ret = parser.parse(result, target_file)
            if not ret:
                # 解析失败
                logger.error(f"parsing {title} error")
                continue
            _, desc, content = ret

            # 调用内容解析器进行解析
            filedata = self.content_parser.parse(result, title, desc, content)
            if not filedata:
                continue

            # 获取输出路径
            output_path = self.__get_law_output_path(title, item["publish"])
            logger.debug(f"parsing {title} success")
            # 将解析结果写入缓存
            self.cache.write_law(output_path, filedata)

    def parse_file(self, file_path, publish_at=None):
        # 定义一个空字典result，用于存储解析出来的数据
        result = {}
        # 以只读模式打开文件
        with open(file_path, "r") as f:
            # 读取文件内容，并使用lambda函数过滤掉空字符串，然后使用map函数去掉每行头尾空白字符
            data = list(filter(lambda x: x, map(lambda x: x.strip(), f.readlines())))
        # 获取文件标题
        title = data[0]
        # 调用content_parser解析文件，并将结果赋值给filedata
        filedata = self.content_parser.parse(result, title, data[1], data[2:])
        # 如果filedata为空，则返回
        if not filedata:
            return
        # 获取输出路径
        output_path = self.__get_law_output_path(title, publish_at)
        # 打印日志
        logger.debug(f"parsing {title} success")
        # 将解析出来的数据写入缓存
        self.cache.write_law(output_path, filedata)

    def get_file_hash(self, title, publish_at=None) -> str:
        # 创建一个md5对象
        _hash = md5()
        # 将title编码成utf8格式，并更新到md5对象中
        _hash.update(title.encode("utf8"))
        # 如果publish_at存在，将publish_at编码成utf8格式，并更新到md5对象中
        if publish_at:
            _hash.update(publish_at.encode("utf8"))
        # 返回md5对象的摘要信息的十六进制表示，取前8位
        return _hash.digest().hex()[0:8]

    def __get_law_output_path(self, title, publish_at: str) -> Path:
        # 获取法的输出路径
        # 参数：title（标题），publish_at（发布日期）
        # 返回：Path

        # 移除标题中的中华人民共和国字样
        title = title.replace("中华人民共和国", "")
        # 初始化路径
        ret = Path(".")
        # 遍历类别
        for category in self.categories:
            # 如果标题在类别中
            if title in category["title"]:
                # 设置路径
                ret = ret / category["category"]
                # 跳出循环
                break
        # hash_hex = self.get_file_hash(title, publish_at)
        # 如果发布日期不为空
        if publish_at:
            # 设置输出文件名
            output_name = f"{title}({publish_at}).md"
        else:
            # 设置输出文件名
            output_name = f"{title}.md"
        # 返回路径
        return ret / output_name

    def lawList(self):
        # 遍历1-59条法律
        for i in range(1, 60):
            # 获取第i条法的列表
            ret = self.request.getLawList(i)
            # 获取法列表中的数据
            arr = ret["result"]["data"]
            # 如果法列表为空，则结束循环
            if len(arr) == 0:
                break
            # 生成法列表的数据
            yield from arr

    def run(self):
        for i in range(1, 5):
            ret = self.request.getLawList(i)
            arr = ret["result"]["data"]
            if len(arr) == 0:
                break
            for item in arr:
                if "publish" in item and item["publish"]:
                    item["publish"] = item["publish"].split(" ")[0]
                if self.is_bypassed_law(item):
                    continue
                # if item["status"] == "9":
                # continue
                self.parse_law(item)
                if self.spec_title is not None:
                    exit(1)

    def remove_duplicates(self):
        # 获取缓存的输出路径
        p = self.cache.OUTPUT_PATH
        # 创建一个Path对象，起始路径为../
        lookup = Path("../")
        # 遍历输出路径下的所有markdown文件
        for file_path in p.glob("*.md"):
            # 使用Path的glob方法，查找lookup路径下的所有markdown文件
            lookup_files = lookup.glob(f"**/**/{file_path.name}")
            # 过滤掉lookup路径下名为scripts的文件夹
            lookup_files = filter(lambda x: "scripts" not in x.parts, lookup_files)
            # 将lookup_files转换为list
            lookup_files = list(lookup_files)
            # 如果lookup_files不为空
            if len(lookup_files) > 0:
                # 删除file_path指向的文件
                os.remove(file_path)
                # 打印删除的文件路径
                print(f"remove {file_path}")


def main():
    req = LawParser()
    args = sys.argv[1:]
    if args:
        req.parse_file(args[0], args[1])
        return
    req.request.searchType = "1,3"
    req.request.params = [
        # ("type", "公安部规章")
        ("xlwj", ["02", "03", "04", "05", "06", "07", "08"]),  # 法律法规
        #  ("fgbt", "最高人民法院、最高人民检察院关于执行《中华人民共和国刑法》确定罪名"),
        # ("fgxlwj", "xzfg"),  # 行政法规
        # ('type', 'sfjs'),
        # ("zdjg", "4028814858a4d78b0158a50f344e0048&4028814858a4d78b0158a50fa2ba004c"), #北京
        # ("zdjg", "4028814858b9b8e50158bed591680061&4028814858b9b8e50158bed64efb0065"), #河南
        # ("zdjg", "4028814858b9b8e50158bec45e9a002d&4028814858b9b8e50158bec500350031"), # 上海
        # ("zdjg", "4028814858b9b8e50158bec5c28a0035&4028814858b9b8e50158bec6abbf0039"), # 江苏
        # ("zdjg", "4028814858b9b8e50158bec7c42f003d&4028814858b9b8e50158beca3c590041"), # 浙江
        # ("zdjg", "4028814858b9b8e50158bed40f6d0059&4028814858b9b8e50158bed4987a005d"),  # 山东
        # ("zdjg", "4028814858b9b8e50158bef1d72600b9&4028814858b9b8e50158bef2706800bd"), # 陕西省
        # (
        #     "zdjg",
        #     "4028814858b9b8e50158beda43a50079&4028814858b9b8e50158bedab7ea007d",
        # ),  # 广东
        # (
        #     "zdjg",
        #     "4028814858b9b8e50158bee5863c0091&4028814858b9b8e50158bee9a3aa0095",
        # )  # 重庆
    ]
    # req.request.req_time = 1647659481879
    req.request.req_time = int(time() * 1000)
    # req.spec_title = "反有组织犯罪法"
    try:
        req.run()
    except KeyboardInterrupt:
        logger.info("keyboard interrupt")
    finally:
        req.remove_duplicates()


if __name__ == "__main__":
    main()
