import scrapy
import sqlite3
import json
from urllib.parse import urljoin
from text_extractor import extract


class USpider(scrapy.Spider):
    start_urls = []
    custom_settings = {'HTTPERROR_ALLOW_ALL': True}
    download_delay = 0.25
    extract_text = False

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        open(f"{self.name}.db", "a+")
        self.conn = sqlite3.connect(f"{self.name}.db")
        cursor = self.conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS links (
        url TEXT PRIMARY KEY NOT NULL,
        type TEXT NOT NULL,
        status INTEGER,
        length INTEGER,
        links INTEGER,
        subdomain TEXT,
        visited INTEGER,
        completed INTEGER )
        """)
        if self.extract_text == "db":
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS texts (
            url TEXT PRIMARY KEY NOT NULL,
            extracted_text TEXT )
            """)
        self.conn.commit()
        for link in cursor.execute("SELECT url FROM links WHERE type = 'internal' AND completed = 0"):
            self.start_urls.append(link[0])

    def parse_link(self, link, start_url):
        if link.startswith("tel:"):
            return {
                "type": "other"
            }
        link = urljoin(start_url, link)
        if link[-1] == '/':
            new_link = link[:-1]
        else:
            new_link = link
        if new_link.startswith("http://"):
            new_link = new_link[7:]
        elif new_link.startswith("https://"):
            new_link = new_link[8:]
        else:
            return {
                "type": "other"
            }
        if new_link.startswith("www."):
            new_link = new_link[4:]
        domain_index = new_link.find(self.allowed_domains[0])
        if domain_index == -1:
            return {
                "type": "external"
            }
        if domain_index == 0:
            return {
                "type": "internal",
                "link": link
            }
        return {
            "type": "subdomain",
            "subdomain": new_link[:domain_index-1]
        }
        
    def parse(self, response):
        result = {
            "type": "internal",
            "status": response.status
        }
        cursor = self.conn.cursor()
        if response.status == 200:
            result["length"] = len(response.body)
            if self.extract_text:
                text = extract(response.body)
                if self.extract_text == "db":
                    cursor.execute(f"""
                    INSERT OR REPLACE INTO texts (url, extracted_text) 
                    VALUES ('{response.url}', '{text.replace("'", '"')}')
                    """)
                    self.conn.commit()
                elif self.extract_text == "file":
                    data = {
                        "url": response.url,
                        "text": text
                    }
                    with open(f"{self.name}_extracted.txt", "at", encoding="utf-8") as file:
                        file.write("%s,\n" % json.dumps(data, ensure_ascii=False))
            try:
                links = response.xpath("//a/@href").extract()
            except:
                links = []
            result["links"] = len(links)
        else:
            links = []
        cursor.execute(f"""
        INSERT OR REPLACE INTO links (
        url, {", ".join([key for key in result])}, visited, completed) 
        VALUES (
        '{response.url}', 
        {", ".join([f"'{result[key]}'" if type(result[key] == str) else str(result[key]) for key in result])}, 1, 0)
        """)
        self.conn.commit()
        yield {response.url: result}
        for link in links:
            parsed_url = self.parse_link(link, response.url)
            cursor.execute(f"SELECT COUNT(*) FROM links WHERE url='{parsed_url.get('link', link)}'")
            if cursor.fetchall()[0][0]:
                continue
            try:
                cursor.execute(f"""
                INSERT INTO links (url, type, visited, completed) 
                VALUES (
                '{parsed_url.get("link", link)}',
                '{parsed_url["type"]}',
                0,
                0)
                """)
                self.conn.commit()
            except sqlite3.IntegrityError:
                print(f"IntegrityError. {parsed_url.get('link', link)}")
                continue
            if parsed_url["type"] == "internal":
                yield response.follow(parsed_url["link"], self.parse)
            else:
                yield {link: parsed_url}
        cursor.execute(f"UPDATE links SET completed = 1 WHERE url = '{response.url}'")
        self.conn.commit()
