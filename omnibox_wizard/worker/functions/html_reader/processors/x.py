import json
import logging
import re
from urllib.parse import urlparse
from bs4 import BeautifulSoup, Tag
from html2text import html2text
from opentelemetry import trace

from wizard_common.worker.entity import GeneratedContent, Image
from omnibox_wizard.worker.functions.html_reader.processors.base import (
    HTMLReaderBaseProcessor,
)

tracer = trace.get_tracer("XProcessor")
logger = logging.getLogger(__name__)


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
        soup = self._clean_comment_section(soup)

        if soup.select_one('div[data-testid="twitterArticleReadView"]'):
            result = self._convert_article(soup)
        else:
            tweet_containers = self._find_relevant_tweet_containers(soup)
            if tweet_containers:
                result = self._convert_tweet_thread(tweet_containers)
            else:
                main_tweet_container = self._find_main_tweet_container(soup)
                if main_tweet_container:
                    result = self._convert_tweet(main_tweet_container)
                else:
                    result = self._convert_tweet(soup)

        if not self._has_effective_content(result):
            metadata_result = self._convert_metadata(soup)
            if metadata_result:
                result = metadata_result

        if result.images:
            image_links = [(img.link, img.name) for img in result.images]
            downloaded_images = await self.get_images(image_links)
            result.images = downloaded_images
        return result

    def _find_main_tweet_container(self, soup: BeautifulSoup) -> Tag | None:
        main_cell = self._find_main_content_cell(soup)
        if main_cell:
            for tweet in main_cell.find_all(attrs={"data-testid": "tweet"}):
                if not tweet.find_parent(attrs={"data-testid": "tweet"}):
                    return tweet

        primary_column = soup.select_one('[data-testid="primaryColumn"]')
        if not primary_column:
            return None

        for tweet in primary_column.find_all(attrs={"data-testid": "tweet"}):
            if tweet.find_parent(attrs={"data-testid": "tweet"}):
                continue
            return tweet

        return None

    def _find_relevant_tweet_containers(self, soup: BeautifulSoup) -> list[Tag]:
        primary_column = soup.select_one('[data-testid="primaryColumn"]')
        if not primary_column:
            return []

        tweets = []
        for cell in primary_column.find_all(attrs={"data-testid": "cellInnerDiv"}):
            for tweet in cell.find_all(attrs={"data-testid": "tweet"}):
                if tweet.find_parent(attrs={"data-testid": "tweet"}):
                    continue
                tweets.append(tweet)
                break

        return tweets

    def _extract_tweet_username(self, tweet: Tag) -> str:
        user_name = tweet.find(attrs={"data-testid": "User-Name"})
        if not user_name:
            return ""

        username_match = re.search(r"@[\w]+", user_name.get_text(" ", strip=True))
        if not username_match:
            return ""

        return username_match.group()

    def _find_quote_link_card(self, tweet: Tag) -> Tag | None:
        for link in tweet.find_all(attrs={"role": "link"}):
            if (
                link.find(attrs={"data-testid": "User-Name"})
                and link.find(attrs={"data-testid": "Tweet-User-Avatar"})
                and link.find(attrs={"data-testid": "tweetText"})
            ):
                return link
        return None

    def _extract_quote_link_card(self, card: Tag) -> tuple[str, list[Image]]:
        quote_parts = []
        quote_images = []

        user_name = card.find(attrs={"data-testid": "User-Name"})
        if user_name:
            username_match = re.search(r"@[\w]+", user_name.get_text(" ", strip=True))
            if username_match:
                quote_parts.append(username_match.group())

        tweet_text = card.find(attrs={"data-testid": "tweetText"})
        if tweet_text:
            tweet_content = tweet_text.get_text(strip=True)
            if tweet_content:
                quote_parts.append(tweet_content)

        for img in card.find_all("img"):
            src = img.get("src", "")
            alt = img.get("alt", src)
            if self._is_content_image(src):
                quote_parts.append(f"![{alt}]({src})")
                quote_images.append(
                    Image.model_validate(
                        {
                            "name": alt,
                            "link": src,
                            "data": "",
                            "mimetype": "",
                        }
                    )
                )

        if not quote_parts:
            return "", []

        return self._format_quote_block("", quote_parts), quote_images

    def _extract_article_card_text(self, article_cover: Tag) -> tuple[str, str]:
        article_parent = article_cover.parent
        if not article_parent:
            return "", ""

        text_container = None
        for child in article_parent.find_all("div", recursive=False):
            if child is article_cover:
                continue
            if child.get_text(strip=True):
                text_container = child
                break

        if not text_container:
            return "", ""

        text_blocks = [
            child.get_text(" ", strip=True)
            for child in text_container.find_all("div", recursive=False)
            if child.get_text(strip=True)
        ]

        title = text_blocks[0] if text_blocks else ""
        summary = text_blocks[1] if len(text_blocks) > 1 else ""

        if not summary:
            summary_block = text_container.find(
                lambda tag: (
                    isinstance(tag, Tag)
                    and tag.name == "div"
                    and "-webkit-line-clamp" in (tag.get("style") or "")
                )
            )
            if summary_block:
                summary = summary_block.get_text(" ", strip=True)

        return title, summary

    def _extract_quote_info(self, soup: BeautifulSoup | Tag) -> tuple[str, list[Image]]:
        logger.debug("Start extracting quote information")

        article_cover = soup.find("div", attrs={"data-testid": "article-cover-image"})
        if article_cover:
            logger.debug("Detected article quote (article-cover-image found)")

            current = article_cover
            quote_container = None

            for _ in range(15):
                if current and current.parent:
                    current = current.parent
                    if current.find("div", attrs={"data-testid": "Tweet-User-Avatar"}):
                        quote_container = current
                        break
                else:
                    break

            if not quote_container:
                trace.get_current_span().set_attribute("x.quote_container_found", False)
                return "", []

            result_parts = []
            quote_images = []
            user_name_div = quote_container.find(
                "div", attrs={"data-testid": "User-Name"}
            )
            if user_name_div:
                all_text = user_name_div.get_text()
                username_match = re.search(r"@[\w]+", all_text)
                if username_match:
                    username = username_match.group()
                    result_parts.append(username)

            article_title, article_summary = self._extract_article_card_text(
                article_cover
            )
            if article_title:
                result_parts.append(article_title)
            if article_summary:
                result_parts.append(article_summary)

            for img in quote_container.find_all("img"):
                if src := img.get("src"):
                    if self._is_content_image(src):
                        alt = img.get("alt", src)
                        result_parts.append(f"![{alt}]({src})")
                        quote_images.append(
                            Image.model_validate(
                                {
                                    "name": alt,
                                    "link": src,
                                    "data": "",
                                    "mimetype": "",
                                }
                            )
                        )

            if result_parts:
                return self._format_quote_block("", result_parts), quote_images
            return "", []
        else:
            logger.debug("No article cover found, trying tweet quote extraction")
            tweet = self._get_tweet_node(soup) if isinstance(soup, Tag) else None
            if tweet:
                quote_card = self._find_quote_link_card(tweet)
                if quote_card:
                    return self._extract_quote_link_card(quote_card)

            tweet_boundary = tweet
            main_tweet_text = (
                self._find_main_tweet_text(tweet_boundary)
                if tweet_boundary
                else soup.select_one("div[data-testid=tweetText]")
            )

            if not main_tweet_text:
                return "", []

            quote_containers = []

            for avatar in soup.find_all(
                "div", attrs={"data-testid": "Tweet-User-Avatar"}
            ):
                current = avatar.parent
                for _ in range(10):
                    if not current:
                        break

                    tweet_text = current.find("div", attrs={"data-testid": "tweetText"})
                    if tweet_text and tweet_text != main_tweet_text:
                        if current not in quote_containers:
                            quote_containers.append(current)
                            break

                    if current is tweet_boundary:
                        break
                    current = current.parent

            if not quote_containers:
                logger.debug("No quote tweet containers found")
                return "", []

            logger.debug(f"Found {len(quote_containers)} quote tweets")

            result_parts = []
            quote_images = []
            for quote_container in quote_containers:
                user_name_div = quote_container.find(
                    "div", attrs={"data-testid": "User-Name"}
                )
                if user_name_div:
                    all_text = user_name_div.get_text()
                    username_match = re.search(r"@[\w]+", all_text)
                    if username_match:
                        username = username_match.group()
                        result_parts.append(username)

                for img in quote_container.find_all("img"):
                    if src := img.get("src"):
                        if self._is_content_image(src):
                            alt = img.get("alt", src)
                            result_parts.append(f"![{alt}]({src})")
                            quote_images.append(
                                Image.model_validate(
                                    {
                                        "name": alt,
                                        "link": src,
                                        "data": "",
                                        "mimetype": "",
                                    }
                                )
                            )

                tweet_text = quote_container.find(
                    "div", attrs={"data-testid": "tweetText"}
                )
                if tweet_text:
                    tweet_content = tweet_text.get_text(strip=True)
                    if tweet_content:
                        result_parts.append(tweet_content)
            if result_parts:
                return self._format_quote_block("", result_parts), quote_images
            return "", []

    def _get_tweet_node(self, tweet_container: BeautifulSoup | Tag) -> Tag | None:
        if (
            isinstance(tweet_container, Tag)
            and tweet_container.get("data-testid") == "tweet"
        ):
            return tweet_container
        return tweet_container.select_one('[data-testid="tweet"]')

    def _is_nested_tweet_text(self, tweet_text: Tag, tweet: Tag) -> bool:
        current = tweet_text.parent
        while current and current is not tweet:
            if current.get("data-testid") in {"simpleTweet", "tweet"}:
                return True
            if current.get("role") == "link" and (
                current.find(attrs={"data-testid": "User-Name"})
                or current.find(attrs={"data-testid": "Tweet-User-Avatar"})
            ):
                return True
            current = current.parent
        return False

    def _find_main_tweet_text(self, tweet: Tag) -> Tag | None:
        for tweet_text in tweet.find_all(attrs={"data-testid": "tweetText"}):
            if self._is_nested_tweet_text(tweet_text, tweet):
                continue
            return tweet_text
        return None

    def _is_content_image(self, src: str) -> bool:
        return bool(
            src
            and "profile_images" not in src
            and "emoji" not in src
            and "abs.twimg.com/emoji" not in src
        )

    def _format_quote_block(self, title: str, parts: list[str]) -> str:
        lines = []
        if title:
            lines.extend([title, ""])

        for part in parts:
            lines.extend(part.splitlines() or [""])

        return "\n".join(f"> {line}" if line else ">" for line in lines)

    def _is_tweet_action_group(self, group: Tag) -> bool:
        return bool(
            group.get("role") == "group"
            and group.find(attrs={"data-testid": "reply"})
            and group.find(attrs={"data-testid": "retweet"})
            and group.find(attrs={"data-testid": "like"})
        )

    def _find_main_content_cell(self, soup: BeautifulSoup) -> Tag | None:
        primary_column = soup.select_one('[data-testid="primaryColumn"]')
        if not primary_column:
            return None

        for group in primary_column.find_all(attrs={"role": "group"}):
            if not self._is_tweet_action_group(group):
                continue

            cell = group.find_parent(attrs={"data-testid": "cellInnerDiv"})
            if cell:
                return cell

        return None

    def _cell_has_tweet_content(self, cell: Tag) -> bool:
        return bool(
            cell.find(attrs={"data-testid": "tweet"})
            and (
                cell.find(attrs={"data-testid": "tweetText"})
                or cell.find(attrs={"data-testid": "tweetPhoto"})
                or cell.find(attrs={"data-testid": "twitterArticleReadView"})
                or cell.find(attrs={"data-testid": "longformRichTextComponent"})
            )
        )

    def _has_effective_content(self, result: GeneratedContent) -> bool:
        return bool((result.markdown or "").strip() or result.images)

    def _convert_metadata(self, soup: BeautifulSoup) -> GeneratedContent | None:
        posting = self._find_social_media_posting(soup)
        if not posting:
            return None

        text = (posting.get("articleBody") or "").strip()
        if not text:
            return None

        author = posting.get("author") or {}
        author_handle = author.get("alternateName") or ""
        author_name = author.get("name") or ""

        image_urls = self._normalize_metadata_images(posting.get("image"))

        markdown_parts = []
        if author_handle:
            markdown_parts.append(author_handle)
        elif author_name:
            markdown_parts.append(author_name)

        markdown_parts.append(text)

        images = [
            Image.model_validate(
                {
                    "name": image_url,
                    "link": image_url,
                    "data": "",
                    "mimetype": "",
                }
            )
            for image_url in image_urls
            if self._is_content_image(image_url)
        ]

        for image in images:
            markdown_parts.append(f"![{image.name}]({image.link})")

        markdown = "\n\n".join(markdown_parts).strip()
        title = text.splitlines()[0].strip() if text else None

        return GeneratedContent(title=title, markdown=markdown, images=images or None)

    def _find_social_media_posting(self, soup: BeautifulSoup) -> dict | None:
        for script in soup.select('script[type="application/ld+json"]'):
            raw = script.string or script.get_text()
            if not raw:
                continue

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            posting = self._search_social_media_posting(data)
            if posting:
                return posting

        return None

    def _search_social_media_posting(self, data) -> dict | None:
        if isinstance(data, dict):
            if data.get("@type") == "SocialMediaPosting":
                return data

            for value in data.values():
                posting = self._search_social_media_posting(value)
                if posting:
                    return posting

        if isinstance(data, list):
            for item in data:
                posting = self._search_social_media_posting(item)
                if posting:
                    return posting

        return None

    def _normalize_metadata_images(self, value) -> list[str]:
        if isinstance(value, str):
            return [value]

        if isinstance(value, list):
            return [item for item in value if isinstance(item, str)]

        if isinstance(value, dict):
            url = value.get("url")
            return [url] if isinstance(url, str) else []

        return []

    def _convert_tweet_thread(self, tweet_containers: list[Tag]) -> GeneratedContent:
        contents = []
        images = []
        title = None
        seen_images = set()

        for tweet in tweet_containers:
            result = self._convert_tweet(tweet)
            username = self._extract_tweet_username(tweet)
            markdown = result.markdown.strip()

            if username:
                markdown = f"{username}\n\n{markdown}"
            if markdown:
                contents.append(markdown)
            if not title and result.title:
                title = result.title

            for image in result.images or []:
                if image.link in seen_images:
                    continue
                seen_images.add(image.link)
                images.append(image)

        return GeneratedContent(
            title=title,
            markdown="\n\n---\n\n".join(contents),
            images=images or None,
        )

    def _convert_tweet(self, tweet_container: BeautifulSoup | Tag) -> GeneratedContent:
        quote_info, quote_images = self._extract_quote_info(tweet_container)
        tweet = self._get_tweet_node(tweet_container)
        content = self._find_main_tweet_text(tweet) if tweet else None
        quote_images_links = {img.link for img in quote_images}
        images: list[Image] = []

        if tweet:
            for img in tweet.find_all("img"):
                if src := img.get("src"):
                    if self._is_content_image(src):
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
            for img in content.find_all("img"):
                if "abs.twimg.com/emoji" in (img.get("src", "")):
                    img.replace_with(img.get("alt", ""))
            content_with_br: str = str(content).replace("\n", "<br>\n")
            content_with_br = content_with_br.replace('href="/', 'href="https://x.com/')
            markdown = html2text(content_with_br, bodywidth=0) + "\n\n" + markdown
            markdown = "\n".join(map(lambda x: x.strip(), markdown.split("\n")))
        title = next(
            (
                line.strip()
                for line in markdown.split("\n")
                if line.strip()
                and not line.strip().startswith("![")
                and not line.strip().startswith(">")
            ),
            None,
        )
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
                    title_in_child = child.select_one(
                        '[data-testid="twitter-article-title"]'
                    )
                    if not title_in_child:
                        imgs = child.find_all("img")
                        for img in imgs:
                            src = img.get("src", "")
                            alt = img.get("alt", "")
                            if self._is_content_image(src):
                                title_images.append(
                                    Image.model_validate(
                                        {
                                            "name": alt,
                                            "link": src,
                                            "data": "",
                                            "mimetype": "",
                                        }
                                    )
                                )

        content_div = soup.select_one('div[data-testid="longformRichTextComponent"]')
        if not content_div:
            return GeneratedContent(
                title=title, markdown="", images=title_images or None
            )

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
                markdown_parts.append(f"## {h2_text}")
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
                    logger.debug(
                        "Found simpleTweet in section, calling _extract_article_quote"
                    )
                    quote_info, quote_images = self._extract_article_quote(block)
                    logger.debug(
                        f"Article quote extraction result: quote_info_length={len(quote_info) if quote_info else 0}, quote_images_count={len(quote_images)}"
                    )
                    if quote_info:
                        markdown_parts.append(quote_info)
                        images.extend(quote_images)
                    continue
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
                    if self._is_content_image(src):
                        markdown_parts.append(f"![{alt}]({src})")
                        images.append(
                            Image.model_validate(
                                {"name": alt, "link": src, "data": "", "mimetype": ""}
                            )
                        )
                        continue
        markdown = "\n\n".join(markdown_parts)
        all_images = title_images + images
        return GeneratedContent(
            title=title, markdown=markdown, images=all_images or None
        )

    def _extract_article_quote(self, block: Tag) -> tuple[str, list[Image]]:
        logger.debug("Start processing article quote extraction")
        simple_tweet = block.select_one('[data-testid="simpleTweet"]')
        if not simple_tweet:
            return "", []

        article_cover = simple_tweet.select_one('[data-testid="article-cover-image"]')

        quote_parts = []
        quote_images = []

        if article_cover:
            logger.debug("Detected article quote in _extract_article_quote")
            author_div = simple_tweet.select_one('[data-testid="User-Name"]')
            if author_div:
                author_text = author_div.get_text(strip=True)
                username_match = re.search(r"@[\w]+", author_text)
                if username_match:
                    quote_parts.append(username_match.group())

            article_title, article_summary = self._extract_article_card_text(
                article_cover
            )
            if article_title:
                quote_parts.append(article_title)
            if article_summary:
                quote_parts.append(article_summary)

            for img in simple_tweet.find_all("img"):
                src = img.get("src", "")
                alt = img.get("alt", "")
                if self._is_content_image(src):
                    quote_parts.append(f"![{alt}]({src})")

                    quote_images.append(
                        Image.model_validate(
                            {"name": alt, "link": src, "data": "", "mimetype": ""}
                        )
                    )
        else:
            logger.debug("Detected tweet quote in _extract_article_quote")
            author_div = simple_tweet.select_one('[data-testid="User-Name"]')
            if author_div:
                all_text = author_div.get_text()
                username_match = re.search(r"@[\w]+", all_text)
                if username_match:
                    username = username_match.group()
                    quote_parts.append(username)

            tweet_text_div = simple_tweet.select_one('[data-testid="tweetText"]')
            if tweet_text_div:
                tweet_content = tweet_text_div.get_text(strip=True)
                if tweet_content:
                    quote_parts.append(tweet_content)

            for img in simple_tweet.find_all("img"):
                src = img.get("src", "")
                alt = img.get("alt", "")
                if self._is_content_image(src):
                    quote_parts.append(f"![{alt}]({src})")
                    quote_images.append(
                        Image.model_validate(
                            {"name": alt, "link": src, "data": "", "mimetype": ""}
                        )
                    )

        if quote_parts:
            logger.debug(f"Returning quote content with {len(quote_parts)} parts")
            return self._format_quote_block("", quote_parts), quote_images

        trace.get_current_span().set_attribute("x.quote_parts_empty", True)
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

    def _clean_comment_section(self, soup: BeautifulSoup) -> BeautifulSoup:
        primary_column = soup.select_one('[data-testid="primaryColumn"]')
        main_cell = self._find_main_content_cell(soup)
        if not primary_column or not main_cell:
            return soup

        cells = primary_column.find_all(attrs={"data-testid": "cellInnerDiv"})
        reached_main = False
        removing = False

        for cell in cells:
            if cell == main_cell:
                reached_main = True
                continue

            if not reached_main:
                continue

            if removing:
                cell.decompose()
                continue

            if self._cell_has_tweet_content(cell):
                continue

            removing = True
            cell.decompose()
        return soup
