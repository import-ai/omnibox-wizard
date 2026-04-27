from urllib.parse import urlparse
import re
from bs4 import BeautifulSoup, Tag
from html2text import html2text
from opentelemetry import trace

from wizard_common.worker.entity import GeneratedContent, Image
from omnibox_wizard.worker.functions.html_reader.processors.base import (
    HTMLReaderBaseProcessor,
)

tracer = trace.get_tracer("XProcessor")


class XProcessor(HTMLReaderBaseProcessor):
    def hit(self, html: str, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.netloc == "x.com":
            if "/status/" in parsed.path:
                return True
        return False

    @tracer.start_as_current_span("XProcessor.convert")
    async def convert(self, html: str, url: str) -> GeneratedContent:
        soup = BeautifulSoup(html, "html.parser")

        if soup.select_one('div[data-testid="twitterArticleReadView"]'):
            return self._convert_article(soup)
        return self._convert_tweet(soup)
    
    def _extract_quote_info(self,soup) -> tuple[str, list[Image]]:
        print(f"DEBUG: 开始提取引用信息")

        article_cover = soup.find('div', attrs={'data-testid': 'article-cover-image'})
        if article_cover:
            print(f"DEBUG: 找到 article-cover-image, 处理文章引用")
            current = article_cover
            quote_container = None
            
            current = article_cover
            quote_container = None

            for i in range(15):
                if current and current.parent:
                    current = current.parent
                    if current.find('div', attrs={'data-testid': 'Tweet-User-Avatar'}):
                        quote_container = current
                        print(f"DEBUG: 找引用容器, 在第{i+1}层")
                        break
                else:
                    break
            
            if not quote_container:
                print(f"DEBUG: 没有找到包含头像的引用容器")
                return "", []
            
            result_parts = []
            quote_images = []
            user_name_div = quote_container.find('div', attrs={'data-testid': 'User-Name'})
            if user_name_div:
                all_text = user_name_div.get_text()
                print(f"DEBUG: User-Name 容器文字: {all_text[:100]}")
                username_match = re.search(r'@[\w]+', all_text)
                if username_match:
                    username = username_match.group()
                    result_parts.append(username)
                    print(f"DEBUG: 找到用户名: {username}")
                else:
                    print(f"DEBUG: 没有找到 @ 开头的用户名")
            
            if article_cover.parent:
                siblings = article_cover.parent.find_all('div', recursive=False)
                print(f"DEBUG: 找到 {len(siblings)}个兄弟div")
                for i, div in enumerate(siblings):
                    if div != article_cover:
                        title_spans = div.find_all('span', class_='css-1jxf684')
                        print(f"DEBUG: 第{i+1} 个兄弟div找到 {len(title_spans)} 个span")
                        for span in title_spans:
                            text = span.get_text(strip=True)
                            print(f"DEBUG: 检查文字: {text[:50]}")
                            if text and '文章' not in text and len(text) < 100 and len(text) > 5:
                                article_title = text
                                result_parts.append(f"引用文章: {article_title}")
                                print(f"DEBUG: 找到文章标题")
                                break
                        if any("引用文章:" in part for part in result_parts):
                            break
        
            if article_cover.parent:
                siblings = article_cover.parent.find_all('div', recursive=False)
                for i, div in enumerate(siblings):
                    style = div.get('style', '')
                    if '-webkit-line-clamp' in style:
                        summary_span = div.find('span', class_='css-1jxf684')
                        if summary_span:
                            summary_text = summary_span.get_text(strip=True)
                            if summary_text and len(summary_text) > 20:
                                result_parts.append(f"摘要: {summary_text}")
                                print(f"DEBUG: 找到文章摘要: {summary_text[:50]}...")
                                break
            print(f"DEBUG: result_parts = {result_parts}")
            for img in quote_container.find_all("img"):
                if src := img.get("src"):
                    if "profile_images" not in src and "emoji" not in src:
                        alt = img.get("alt", src)
                        result_parts.append(f"![{alt}]({src})")
                        quote_images.append(
                            Image.model_validate({
                                "name": alt,
                                "link": src,
                                "data": "",
                                "mimetype": "",
                            })
                        )
                        print(f"DEBUG: 添加文章封面图片: {src[:50]}...")

            if result_parts:
                result = "--- 引用的文章 ---\n" + "\n\n".join(result_parts)
                return result, quote_images
            print(f"DEBUG: result_parts为空")
            return "", []
        else:
            print(f"DEBUG: 没有找到 article-cover-image尝试查找普通推文引用")
            main_tweet_text = soup.select_one("div[data-testid=tweetText]")

            if not main_tweet_text:
                print(f"DEBUG: 没有找到推文,无法确定引用推文")
                return "", []
            
            quote_containers = []

            for avatar in soup.find_all('div', attrs={'data-testid': 'Tweet-User-Avatar'}):
                current = avatar.parent
                for depth in range(10):
                    if current:
                        tweet_text = current.find('div', attrs={'data-testid': 'tweetText'})
                        if tweet_text and tweet_text != main_tweet_text:
                            if current not in quote_containers:
                                quote_containers.append(current)
                                print(f"DEBUG: 找到候选引用容器, 在第{depth}层")
                                break
                        current = current.parent
            
            if not quote_containers:
                print(f"DEBUG: 没有找到引用推文容器")
                return "", []
            
            print(f"DEBUG: 找到 {len(quote_containers)} 个引用推文")

            result_parts = []
            quote_images = []
            for i, quote_container in enumerate(quote_containers):
                print(f"DEBUG: 处理第{i+1}个引用推文")

                for img in quote_container.find_all("img"):
                    if src := img.get("src"):
                        if "profile_images" not in src and "emoji" not in src:
                            quote_images.append(
                                Image.model_validate({
                                    "name": img.get("alt", src),
                                    "link": src,
                                    "data": "",
                                    "mimetype": "",
                                })
                            )
                            print(f"DEBUG: 找到引用图片: {src[:50]}...")

                user_name_div = quote_container.find('div', attrs={'data-testid': 'User-Name'})
                if user_name_div:
                    all_text = user_name_div.get_text()
                    username_match = re.search(r'@[\w]+', all_text)
                    if username_match:
                        username = username_match.group()
                        result_parts.append(username)
                        print(f"DEBUG: 找到用户名: {username}")
                
                for img in quote_container.find_all("img"):
                        if src := img.get("src"):
                            if "profile_images" not in src and "emoji" not in src:
                                alt = img.get("alt", src)
                                result_parts.append(f"![{alt}]({src})")
                                print(f"DEBUG: 添加引用图片到文本: {src[:50]}...")

                tweet_text = quote_container.find('div', attrs={'data-testid': 'tweetText'})
                if tweet_text:
                    tweet_content = tweet_text.get_text(strip=True)
                    if tweet_content:
                        result_parts.append(f"引用内容: {tweet_content}")
                        print(f"DEBUG: 找到推文引用内容: {tweet_content[:50]}...")
            
            print(f"DEBUG: result_parts = {result_parts}")
            if result_parts:
                result = "--- 引用的帖子 ---\n" + "\n\n".join(result_parts),quote_images
                return result
            print(f"DEBUG: result_parts为空")
            return "", []

    def _convert_tweet(self, soup) -> GeneratedContent:
        quote_info, quote_images = self._extract_quote_info(soup)
        content: Tag = soup.select_one("div[data-testid=tweetText]")
        quote_images_links = {img.link for img in quote_images}
        images: list[Image] = []
        tweet = soup.select_one('[data-testid="tweet"]')
        if tweet:
            for img in tweet.find_all("img"):
                if src := img.get("src"):
                    if "profile_images" not in src and "emoji" not in src:
                        if src not in quote_images_links:
                            images.append(
                                Image.model_validate(
                                    {
                                        "name": img.get("alt", src),
                                        "link": src,
                                        "data": "",
                                        "mimetype": "",
                                    }
                                )
                            )
                            
        markdown: str = "\n\n".join(
            [
                f"![{image.name or (i + 1)}]({image.link})"
                for i, image in enumerate(images)
            ]
        )
        if content:
            content_with_br: str = str(content).replace("\n", "<br>\n")
            content_with_br = content_with_br.replace('href="/','href="https://x.com/')
            markdown = html2text(content_with_br, bodywidth=0) + "\n\n" + markdown
            markdown = "\n".join(map(lambda x: x.strip(), markdown.split("\n")))
        title: str = next(filter(lambda x: bool(x.strip()), markdown.split("\n")))
        images.extend(quote_images)
        if quote_info:
            markdown = markdown.rstrip("\n") + "\n\n" + quote_info
        return GeneratedContent(title=title, markdown=markdown, images=images or None)

    def _convert_article(self, soup) -> GeneratedContent:
        title_tag = soup.select_one('div[data-testid="twitter-article-title"]')
        title = title_tag.get_text(strip=True) if title_tag else ""

        title_images = []
        article_view = soup.select_one('div[data-testid="twitterArticleReadView"]')
        if article_view:
            for child in article_view.children:
                if isinstance(child, Tag):
                    title_in_child = child.select_one('[data-testid="twitter-article-title"]')
                    if not title_in_child:
                        imgs = child.find_all('img')
                        for img in imgs:
                            src = img.get("src", "")
                            alt = img.get("alt", "")
                            if src and "profile_images" not in src and "emoji" not in src:
                                title_images.append(Image.model_validate({
                                    "name": alt,
                                    "link": src,
                                    "data": "",
                                    "mimetype": ""
                                }))
        
        content_div = soup.select_one('div[data-testid="longformRichTextComponent"]')
        if not content_div:
            return GeneratedContent(title=title, markdown="", images=title_images or None)
        
        contents_div = content_div.select_one('[data-contents="true"]')
        if contents_div:
            blocks = contents_div.find_all(recursive=False)
        else:
            blocks = content_div.find_all(attrs={"data-block": "true"})
        
        markdown_parts = []
        images = []

        for img in title_images:
            markdown_parts.append(f"![{img.name}]({img.link})")

        for block in blocks:
            classes = block.get("class", [])
            tag_name = block.name

            if "longform-unstyled" in classes:
                text = self._get_article_block_text(block)
                if text:
                    markdown_parts.append(text)
            elif block.select_one("h2.longform-header-two"):
                h2_text = block.select_one("h2").get_text(strip=True)
                markdown_parts.append(f'## {h2_text}')
            elif tag_name == "blockquote":
                text = self._get_article_block_text(block)
                if text:
                    quoted = "\n".join(f"> {line}" for line in text.split("\n"))
                    markdown_parts.append(quoted)
            elif tag_name == "ol":
                for j, li in enumerate(block.find_all("li", recursive=False)):
                    text = self._get_article_block_text(li)
                    if text:
                        markdown_parts.append(f"{j + 1}. {text}")
            elif tag_name == "ul":
                for li in block.find_all("li", recursive=False):
                    text = self._get_article_block_text(li)
                    if text:
                        markdown_parts.append(f"- {text}")
            elif tag_name == "section":
                simple_tweet = block.select_one('[data-testid="simpleTweet"]')
                if simple_tweet:
                    print(f"DEBUG: 在seciton中找到的simpleTweet, 将调用_extract_article_quote")
                    quote_info, quote_images = self._extract_article_quote(block)
                    print(f"DEBUG: _extract_article_quote返回结果: quote_info长度={len(quote_info) if quote_info else 0}, quote_images数量={len(quote_images)}")
                    if quote_info:
                        markdown_parts.append(quote_info)
                        images.extend(quote_images)
                    continue
                else:
                    print(f"DEBUG: 在section中没找到simpleTweet")
                code = block.select_one("pre code")
                if code:
                    code_classes = code.get("class", [])
                    lang = ""
                    for cls in code_classes:
                        if cls.startswith("language-"):
                            lang = cls.replace("language-", "")
                            break
                    code_text = code.get_text()
                    markdown_parts.append(f"```{lang}\n{code_text}\n```")
                    continue
                
                img = block.select_one("img")
                if img:
                    src = img.get("src", "")
                    alt = img.get("alt", "")
                    if src and "profile_images" not in src and "emoji" not in src:
                        markdown_parts.append(f"![{alt}]({src})")
                        images.append(Image.model_validate({
                            "name": alt,
                            "link": src,
                            "data": "",
                            "mimetype": ""
                        }))
                        continue
        markdown = "\n\n".join(markdown_parts)
        all_images = title_images + images
        return GeneratedContent(title=title, markdown=markdown, images=all_images or None)
    
    def _extract_article_quote(self, block:Tag) -> tuple[str, list[Image]]:
        print(f"DEBUG _extract_article_quote: 开始处理")
        simple_tweet = block.select_one('[data-testid="simpleTweet"]')
        if not simple_tweet:
            return "", []
        
        article_cover = simple_tweet.select_one('[data-testid="article-cover-image"]')

        quote_parts = []
        quote_images = []

        if article_cover:
            print(f"DEBUG _extract_article_quote:检测到文章引用")
            author_div = simple_tweet.select_one('[data-testid="User-Name"]')
            if author_div:
                print(f"DEBUG _extract_article_quote: 找到User-Name")
                author_text = author_div.get_text(strip=True)
                username_match = re.search(r'@[\w]+', author_text)
                if username_match:
                    quote_parts.append(username_match.group())
            
            tweet_content = simple_tweet.get_text(strip=True)
            if tweet_content:
                print(f"DEBUG _extract_article_quote: 推文内容: {tweet_content[:100]}")
                if author_div and author_text in tweet_content:
                    tweet_content = tweet_content.replace(author_text, '', 1).strip()
                    quote_parts.append(tweet_content)
            else:
                print(f"DEBUG _extract_article_quote: 推文内容为空")

            for img in simple_tweet.find_all('img'):
                src = img.get("src", "")
                alt = img.get("alt", "")
                if src and "profile_images" not in src and "emoji" not in src:
                    quote_parts.append(f"![{alt}]({src})")

                    quote_images.append(Image.model_validate({
                        "name": alt,
                        "link": src,
                        "data": "",
                        "mimetype": ""
                    }))            
        else:
            print(f"DEBUG _extract_article_quote:检测到推文引用")
            author_div = simple_tweet.select_one('[data-testid="User-Name"]')
            if author_div:
                all_text = author_div.get_text()
                username_match = re.search(r'@[\w]+', all_text)
                if username_match:                             
                    username = username_match.group()          
                    quote_parts.append(username)
                    print(f"DEBUG _extract_article_quote:找到用户名: {username}")
            
            tweet_text_div = simple_tweet.select_one('[data-testid="tweetText"]')
            if tweet_text_div:
                tweet_content = tweet_text_div.get_text(strip=True)
                if tweet_content:
                    quote_parts.append(tweet_content)
                    print(f"DEBUG _extract_article_quote: 找到推文内容: {tweet_content[:50]}...")
            
            for img in simple_tweet.find_all("img"):
                src = img.get("src", "")
                alt = img.get("alt", "")
                if src and "profile_images" not in src and "emoji" not in src:
                    quote_parts.append(f"![{alt}]({src})")
                    quote_images.append(
                        Image.model_validate({
                            "name": alt,
                            "link": src,
                            "data": "",
                            "mimetype": ""
                        })
                    )

        if quote_parts:
            print(f"DEBUG _extract_article_quote: 返回引用内容,长度: {len(quote_parts)}")
            if article_cover:
                return "--- 引用的文章 ---\n" + "\n\n".join(quote_parts) + "\n--- 引用的文章 ---\n",quote_images
            else:
                return "--- 引用的帖子 ---\n" + "\n\n".join(quote_parts) + "\n--- 引用的帖子 ---\n",quote_images
        else:
            print(f"DEBUG _extract_article_quote: quote_parts为空, 返回空内容")
        return "", []

    def _get_article_block_text(self, block: Tag) -> str:
        result_parts = []

        inner_div = block.select_one("div.public-DraftStyleDefault-block")
        if not inner_div:
            inner_div = block
        for child in inner_div.children:
            if isinstance(child, str):
                result_parts.append(child)
            elif isinstance(child, Tag):
                if child.name == "span":
                    result_parts.append(self._parse_article_span(child))
                elif child.name == "div":
                    result_parts.append(self._get_article_block_text(child))
                elif child.name == "a":
                    href = child.get("href", "")
                    link_text = child.get_text(strip=True)
                    if href and link_text:
                        result_parts.append(f"[{link_text}]({href})")
        return "".join(result_parts).strip()
                
    def _parse_article_span(self, span: Tag) -> str:

        style = span.get("style", "")
        is_bold = "font-weight: bold" in (style or "")

        inner_text = ""
        for child in span.children:
            if isinstance(child, str):
                inner_text += child
            elif isinstance(child, Tag):
                if child.name == "span":
                    inner_text += self._parse_article_span(child)
                elif child.name == "a":
                    href = child.get("href", "")
                    link_text = child.get_text(strip=True)
                    if href and link_text:
                        inner_text += f"[{link_text}]({href})"
                    else:
                        inner_text += link_text
                elif child.name == "br":
                    inner_text += "\n"
        
        if is_bold and inner_text.strip():
            return f"**{inner_text}**"
        return inner_text