#!/usr/bin/env python3
"""
WordPress Traffic Generator
- 20 user agents (browse, read, comment)
- 3 admin agents (moderate, reply, create posts with generated images)
- Browser diversity: 80% Chrome, 15% WebKit, 5% Firefox
- Per-browser proxy support for macvlan network access
- Local Ollama LLM for decision making
- Image generation: charts (matplotlib), diagrams, and header images (PIL)
"""

import asyncio
import random
import time
import io
import re
import os
import tempfile
from datetime import datetime
from dataclasses import dataclass, field
from typing import List, Optional, Literal
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from langchain_ollama import OllamaLLM
from langchain_core.prompts import PromptTemplate
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# =============================================================================
# Configuration
# =============================================================================

@dataclass
class Config:
    # WordPress (from environment - required)
    wp_url: str = field(default_factory=lambda: os.environ["WORDPRESS_URL"])
    admin_user: str = field(default_factory=lambda: os.getenv("WP_ADMIN_USER", "admin"))
    admin_password: str = field(default_factory=lambda: os.environ["WP_ADMIN_PASSWORD"])
    
    # Ollama (from environment - required)
    ollama_host: str = field(default_factory=lambda: os.environ["OLLAMA_HOST"])
    ollama_model: str = field(default_factory=lambda: os.getenv("OLLAMA_MODEL", "qwen2.5:14b"))
    
    # Agent counts
    num_users: int = 20
    num_admins: int = 3
    
    # Browser distribution (percentages)
    browser_chrome_pct: float = 0.80
    browser_webkit_pct: float = 0.15
    browser_firefox_pct: float = 0.05
    
    # Proxy settings (squid ports 40001-40023)
    proxy_enabled: bool = True
    proxy_base_port: int = 40001  # Ports 40001-40023 for 23 browsers
    proxy_host: str = "127.0.0.1"
    
    # Session timing
    user_session_min: int = 60    # 1 minute
    user_session_max: int = 180   # 3 minutes
    admin_session_min: int = 120  # 2 minutes  
    admin_session_max: int = 300  # 5 minutes
    
    # Stagger agent starts
    stagger_min: float = 2.0   # seconds between agent starts
    stagger_max: float = 10.0
    
    # Action timing
    between_action_min: float = 1.0
    between_action_max: float = 3.0
    reading_time_min: float = 3.0
    reading_time_max: float = 10.0


BrowserType = Literal["chromium", "webkit", "firefox"]


@dataclass
class AgentConfig:
    """Configuration for a single agent instance"""
    agent_id: str
    agent_type: Literal["user", "admin"]
    browser_type: BrowserType
    proxy_port: Optional[int]
    
    
# =============================================================================
# Browser Manager
# =============================================================================

class BrowserManager:
    """Manages browser instances with type distribution and proxy assignment"""
    
    def __init__(self, config: Config):
        self.config = config
        self.playwright = None
        self.browsers: dict[BrowserType, Browser] = {}
        
    async def start(self):
        """Initialize Playwright and launch browsers"""
        self.playwright = await async_playwright().start()
        
        # Launch each browser type
        launch_args = ['--ignore-certificate-errors']
        
        self.browsers["chromium"] = await self.playwright.chromium.launch(
            headless=True,
            args=launch_args
        )
        self.browsers["webkit"] = await self.playwright.webkit.launch(
            headless=True
        )
        self.browsers["firefox"] = await self.playwright.firefox.launch(
            headless=True
        )
        
        print(f"✓ Browsers launched: Chromium, WebKit, Firefox")
        
    async def stop(self):
        """Close all browsers"""
        for browser in self.browsers.values():
            await browser.close()
        if self.playwright:
            await self.playwright.stop()
            
    async def create_context(self, agent_config: AgentConfig) -> BrowserContext:
        """Create a new browser context for an agent"""
        browser = self.browsers[agent_config.browser_type]
        
        # Context options
        context_options = {
            "viewport": {"width": 1920, "height": 1080},
            "ignore_https_errors": True,
        }
        
        # Set user agent based on browser type
        if agent_config.browser_type == "chromium":
            context_options["user_agent"] = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        elif agent_config.browser_type == "webkit":
            context_options["user_agent"] = (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 "
                "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"
            )
        elif agent_config.browser_type == "firefox":
            context_options["user_agent"] = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) "
                "Gecko/20100101 Firefox/121.0"
            )
            
        # Add proxy if enabled
        if self.config.proxy_enabled and agent_config.proxy_port:
            context_options["proxy"] = {
                "server": f"http://{self.config.proxy_host}:{agent_config.proxy_port}"
            }
            
        return await browser.new_context(**context_options)


# =============================================================================
# Shared LLM Client
# =============================================================================

class LLMClient:
    """Shared Ollama LLM client"""
    
    def __init__(self, config: Config):
        self.llm = OllamaLLM(
            base_url=config.ollama_host,
            model=config.ollama_model,
            temperature=0.7
        )
        
    async def invoke(self, prompt: str) -> str:
        """Thread-safe LLM invocation"""
        return await asyncio.to_thread(self.llm.invoke, prompt)


# =============================================================================
# Base Agent
# =============================================================================

class BaseAgent:
    """Base class for all agents"""
    
    def __init__(self, agent_config: AgentConfig, config: Config, 
                 browser_manager: BrowserManager, llm_client: LLMClient):
        self.agent_config = agent_config
        self.config = config
        self.browser_manager = browser_manager
        self.llm = llm_client
        
        self.session_start: float = 0
        self.session_duration: float = 0
        self.action_count: int = 0
        
    def log(self, msg: str):
        """Log with agent prefix"""
        print(f"[{self.agent_config.agent_id}] {msg}")
        
    async def random_pause(self, min_time: float, max_time: float):
        """Human-like pause"""
        await asyncio.sleep(random.uniform(min_time, max_time))
        
    async def run(self):
        """Main agent loop - override in subclass"""
        raise NotImplementedError


# =============================================================================
# User Agent
# =============================================================================

class UserAgent(BaseAgent):
    """Browses site, reads posts, leaves comments"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        self.visited_urls: set = set()
        self.pages_visited: list = []
        self.comments_made: int = 0
        
        # Prompts
        self.decision_prompt = PromptTemplate(
            input_variables=["page_content", "available_links", "has_comment_form", 
                           "time_in_session", "pages_visited"],
            template="""You are simulating a realistic website visitor browsing a WordPress blog.

CURRENT PAGE CONTENT (first 800 chars):
{page_content}

AVAILABLE POST LINKS:
{available_links}

COMMENT FORM: {has_comment_form}

SESSION INFO:
- Time browsing: {time_in_session} seconds
- Recently visited: {pages_visited}

What should you do next? Choose ONE action:

1. READ - Keep reading/scrolling this page
2. CLICK_LINK - Click on one of the numbered links above
3. COMMENT - Leave a comment (only if form available)
4. HOMEPAGE - Go back to main page
5. END - Finish browsing

Respond EXACTLY like this:
ACTION: [number 1-5]
LINK_NUMBER: [if ACTION is 2, which link number, otherwise 0]
REASON: [one short sentence]
"""
        )
        
        self.comment_prompt = PromptTemplate(
            input_variables=["post_content"],
            template="""You just read this blog post:

{post_content}

Write a realistic, casual comment (2-3 sentences) as if you're a real person. Be conversational, maybe ask a question or share a brief thought. Don't be overly formal.

Comment:"""
        )
        
    async def run(self):
        """Main user browsing session"""
        self.log(f"🚀 Starting ({self.agent_config.browser_type})")
        
        self.session_start = time.time()
        self.session_duration = random.uniform(
            self.config.user_session_min, 
            self.config.user_session_max
        )
        
        context = await self.browser_manager.create_context(self.agent_config)
        page = await context.new_page()
        
        try:
            self.log(f"🏠 Loading {self.config.wp_url}")
            await page.goto(self.config.wp_url, wait_until='networkidle')
            await self.random_pause(1, 2)
            
            while (time.time() - self.session_start) < self.session_duration:
                self.action_count += 1
                
                # Get page context
                page_info = await self._get_page_info(page)
                self.pages_visited.append(page_info['title'])
                
                # Decide action
                action, link_num = await self._decide_action(page_info)
                
                # Execute
                if action == "read":
                    await self._simulate_reading(page)
                elif action == "click_link":
                    await self._click_link(page, link_num, page_info['links'])
                elif action == "comment":
                    await self._leave_comment(page, page_info)
                elif action == "homepage":
                    await page.goto(self.config.wp_url, wait_until='networkidle')
                elif action == "end_session":
                    break
                    
                await self.random_pause(
                    self.config.between_action_min,
                    self.config.between_action_max
                )
                
        except Exception as e:
            self.log(f"✗ Error: {e}")
        finally:
            await context.close()
            
        duration = time.time() - self.session_start
        self.log(f"✓ Done: {duration:.0f}s, {self.action_count} actions, {self.comments_made} comments")
        
    async def _get_page_info(self, page: Page) -> dict:
        """Extract page content and available actions"""
        title = await page.title()
        
        try:
            content = await page.evaluate("""
                () => {
                    const article = document.querySelector('article, .post, main');
                    if (article) return article.innerText.substring(0, 800);
                    return document.body.innerText.substring(0, 800);
                }
            """)
        except:
            content = ""
            
        try:
            links = await page.evaluate("""
                () => {
                    return Array.from(document.querySelectorAll('a'))
                        .filter(a => {
                            const href = a.getAttribute('href');
                            const text = a.innerText.trim();
                            if (!href || !text || text.length > 100) return false;
                            if (href.includes('wp-admin') || href.includes('wp-login')) return false;
                            if (href.includes('#') || href.startsWith('/')) return false;
                            if (href.includes('/author/') || href.includes('/category/')) return false;
                            if (href.includes('/tag/') || href.includes('/page/')) return false;
                            return href.match(/\\/\\d{4}\\/\\d{2}\\/\\d{2}\\//) || a.getAttribute('rel') === 'bookmark';
                        })
                        .map((a, idx) => ({
                            number: idx + 1,
                            text: a.innerText.trim(),
                            href: a.getAttribute('href')
                        }))
                        .slice(0, 10);
                }
            """)
        except:
            links = []
            
        has_comment_form = await page.query_selector('#comment') is not None
        
        return {
            'title': title,
            'url': page.url,
            'content': content,
            'links': links,
            'has_comment_form': has_comment_form
        }
        
    async def _decide_action(self, page_info: dict) -> tuple:
        """Ask LLM what to do"""
        time_in_session = time.time() - self.session_start
        
        if page_info['links']:
            links_text = "\n".join([
                f"{link['number']}. {link['text'][:60]}"
                for link in page_info['links']
            ])
        else:
            links_text = "(No post links on this page)"
            
        formatted = self.decision_prompt.format(
            page_content=page_info['content'],
            available_links=links_text,
            has_comment_form="Yes" if page_info['has_comment_form'] else "No",
            time_in_session=int(time_in_session),
            pages_visited=', '.join(self.pages_visited[-3:]) if self.pages_visited else 'Homepage only'
        )
        
        response = await self.llm.invoke(formatted)
        
        # Parse response
        action = "read"
        link_number = 0
        
        for line in response.split('\n'):
            if 'ACTION:' in line:
                action_num = line.split(':')[1].strip()
                if '1' in action_num: action = "read"
                elif '2' in action_num: action = "click_link"
                elif '3' in action_num: action = "comment"
                elif '4' in action_num: action = "homepage"
                elif '5' in action_num: action = "end_session"
            if 'LINK_NUMBER:' in line:
                try:
                    link_number = int(line.split(':')[1].strip())
                except:
                    link_number = 1
                    
        return action, link_number
        
    async def _simulate_reading(self, page: Page):
        """Simulate reading with scrolling"""
        scroll_height = await page.evaluate("document.body.scrollHeight")
        viewport_height = await page.evaluate("window.innerHeight")
        
        current_position = 0
        while current_position < scroll_height - viewport_height:
            scroll_amount = random.randint(200, 500)
            current_position += scroll_amount
            await page.evaluate(f"window.scrollTo(0, {current_position})")
            await self.random_pause(0.5, 1.0)
            
        await self.random_pause(
            self.config.reading_time_min,
            self.config.reading_time_max
        )
        
    async def _click_link(self, page: Page, link_number: int, available_links: list):
        """Navigate to a post"""
        if not available_links:
            await page.goto(self.config.wp_url, wait_until='networkidle')
            return
            
        if link_number < 1 or link_number > len(available_links):
            link_number = 1
            
        target = available_links[link_number - 1]
        
        # Skip if already visited
        if target['href'] in self.visited_urls:
            for link in available_links:
                if link['href'] not in self.visited_urls:
                    target = link
                    break
                    
        self.visited_urls.add(target['href'])
        
        try:
            await page.goto(target['href'], wait_until='networkidle')
        except Exception as e:
            self.log(f"⚠️ Navigation failed: {e}")
            
    async def _leave_comment(self, page: Page, page_info: dict):
        """Generate and post comment"""
        if not page_info['has_comment_form']:
            return
            
        formatted = self.comment_prompt.format(post_content=page_info['content'])
        comment_text = await self.llm.invoke(formatted)
        comment_text = comment_text.strip()
        
        try:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await self.random_pause(1, 2)
            
            await page.fill('#comment', comment_text)
            
            author_field = await page.query_selector('#author')
            if author_field:
                await page.fill('#author', f'User_{self.agent_config.agent_id}')
                await page.fill('#email', f'{self.agent_config.agent_id}@example.com')
                
            await page.click('#submit')
            self.comments_made += 1
            self.log(f"💬 Comment posted")
            
        except Exception as e:
            self.log(f"⚠️ Comment failed: {e}")


# =============================================================================
# Admin Agent
# =============================================================================

class AdminAgent(BaseAgent):
    """Moderates comments, replies, creates posts"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        self.comments_approved: int = 0
        self.comments_rejected: int = 0
        self.comments_replied: int = 0
        self.posts_created: int = 0
        
        # Track posts created this session for balancing
        self.session_posts_created = 0
        
        # Prompts
        self.decision_prompt = PromptTemplate(
            input_variables=["pending_comments", "approved_comments", "recent_posts", 
                           "time_in_session", "num_comments", "num_approved"],
            template="""You are a WordPress site administrator balancing content management with content creation.

PENDING COMMENTS TO REVIEW: {pending_comments}
There are {num_comments} pending comments.

APPROVED COMMENTS (can reply to): {approved_comments}
There are {num_approved} approved comments you could reply to.

RECENT POSTS ON SITE:
{recent_posts}

TIME IN SESSION: {time_in_session} seconds

What should you do next? Choose ONE action:

1. APPROVE_COMMENT - Approve a pending comment (specify which number 1-{num_comments})
2. REJECT_COMMENT - Mark a comment as spam (specify which number 1-{num_comments})
3. REPLY_COMMENT - Reply to an approved comment to engage with readers
4. CREATE_POST - Write a new blog post (important for fresh content!)
5. END_SESSION - Done with admin tasks

Balance your time: handle some comments, but also CREATE NEW POSTS regularly. Fresh content keeps the blog alive!
If you've been mostly handling comments, consider creating a post. Aim for at least one new post per session.

Respond EXACTLY like this:
ACTION: [1-5]
ITEM_NUMBER: [if reviewing pending comment (action 1-2), which number 1 to {num_comments}, else 0]
REASON: [one sentence]
"""
        )
        
        self.reply_prompt = PromptTemplate(
            input_variables=["comment_text", "post_title"],
            template="""You are the site admin replying to this comment on your post "{post_title}":

Comment: {comment_text}

Write a friendly, helpful reply (1-2 sentences) as the site owner. Be conversational and appreciative of engagement.

Reply:"""
        )
        
        self.post_prompt = PromptTemplate(
            input_variables=["existing_topics"],
            template="""You run a tech/lifestyle blog. Current topics covered: {existing_topics}

Generate a NEW blog post idea (don't repeat existing topics).

Respond EXACTLY like this:
TITLE: [catchy title]
TOPIC: [one word: tech, lifestyle, tutorial, review, opinion]
IMAGE_TYPE: [chart, diagram, header, infographic]
CONTENT: [write 5-6 substantial paragraphs of blog content, approximately 600-800 words total. Include specific details, examples, and insights.]

Keep it authentic, detailed, and engaging."""
        )
        
    async def run(self):
        """Main admin session"""
        self.log(f"🔐 Starting admin ({self.agent_config.browser_type})")
        
        self.session_start = time.time()
        self.session_duration = random.uniform(
            self.config.admin_session_min,
            self.config.admin_session_max
        )
        
        context = await self.browser_manager.create_context(self.agent_config)
        page = await context.new_page()
        
        try:
            # Login
            await self._login(page)
            
            while (time.time() - self.session_start) < self.session_duration:
                self.action_count += 1
                
                # Get current state
                pending = await self._get_pending_comments(page)
                approved = await self._get_approved_comments(page)
                posts = await self._get_recent_posts(page)
                
                # Force post creation occasionally (20% chance, or 40% if no posts yet this session)
                force_post = False
                if self.session_posts_created == 0 and self.action_count >= 3:
                    # Haven't created a post yet and done a few actions - 40% chance
                    force_post = random.random() < 0.40
                elif random.random() < 0.15:
                    # General 15% chance to create a post
                    force_post = True
                
                if force_post:
                    self.log("📝 Creating post (scheduled)")
                    await self._create_post(page)
                    self.session_posts_created += 1
                    await self.random_pause(
                        self.config.between_action_min,
                        self.config.between_action_max
                    )
                    continue
                
                # Decide action via LLM
                action, item_number = await self._decide_action(pending, approved, posts)
                
                # Execute
                if action in ["approve", "reject"] and pending and item_number > 0:
                    mod_action = "approve" if action == "approve" else "spam"
                    await self._moderate_comment(page, pending[item_number-1]['id'], mod_action)
                elif action == "reply" and approved:
                    comment = random.choice(approved)
                    await self._reply_to_comment(page, comment)
                elif action == "create_post":
                    await self._create_post(page)
                    self.session_posts_created += 1
                elif action == "end":
                    self.log("👋 Ending session")
                    break
                elif not pending and not approved:
                    # No comments at all - create a post instead of ending
                    self.log("📝 No comments, creating post...")
                    await self._create_post(page)
                    self.session_posts_created += 1
                    
                await self.random_pause(
                    self.config.between_action_min,
                    self.config.between_action_max
                )
                
        except Exception as e:
            self.log(f"✗ Error: {e}")
        finally:
            await context.close()
            
        duration = time.time() - self.session_start
        self.log(f"✓ Done: {duration:.0f}s, approved={self.comments_approved}, "
                f"rejected={self.comments_rejected}, replied={self.comments_replied}, "
                f"posts={self.posts_created}")
        
    async def _login(self, page: Page):
        """Login to WordPress admin"""
        self.log("🔑 Logging in...")
        await page.goto(f"{self.config.wp_url}/wp-login.php", wait_until='networkidle')
        await page.fill('#user_login', self.config.admin_user)
        await page.fill('#user_pass', self.config.admin_password)
        await page.click('#wp-submit')
        await page.wait_for_load_state('networkidle')
        self.log("✓ Logged in")
        
    async def _get_pending_comments(self, page: Page) -> list:
        """Get pending comments"""
        await page.goto(
            f"{self.config.wp_url}/wp-admin/edit-comments.php?comment_status=moderated",
            wait_until='networkidle'
        )
        
        try:
            await page.wait_for_selector('table.wp-list-table', timeout=5000)
            comments = await page.evaluate("""
                () => {
                    return Array.from(document.querySelectorAll('tr[id^="comment-"]'))
                        .map((row, idx) => ({
                            number: idx + 1,
                            id: row.id.replace('comment-', ''),
                            author: row.querySelector('.author strong')?.innerText || 'Unknown',
                            content: (row.querySelector('.comment p')?.innerText || '').substring(0, 100)
                        }))
                        .slice(0, 10);
                }
            """)
            return comments
        except:
            return []
            
    async def _get_approved_comments(self, page: Page) -> list:
        """Get approved comments for replying"""
        await page.goto(
            f"{self.config.wp_url}/wp-admin/edit-comments.php?comment_status=approved",
            wait_until='networkidle'
        )
        
        try:
            await page.wait_for_selector('table.wp-list-table', timeout=5000)
            comments = await page.evaluate("""
                () => {
                    return Array.from(document.querySelectorAll('tr[id^="comment-"]'))
                        .map((row, idx) => ({
                            number: idx + 1,
                            id: row.id.replace('comment-', ''),
                            author: row.querySelector('.author strong')?.innerText || 'Unknown',
                            content: (row.querySelector('.comment p')?.innerText || '').substring(0, 100),
                            postTitle: row.querySelector('.column-response a')?.innerText || 'Unknown'
                        }))
                        .slice(0, 5);
                }
            """)
            return comments
        except:
            return []
            
    async def _get_recent_posts(self, page: Page) -> list:
        """Get recent post titles"""
        await page.goto(
            f"{self.config.wp_url}/wp-admin/edit.php",
            wait_until='networkidle'
        )
        
        try:
            await page.wait_for_selector('table.wp-list-table', timeout=5000)
            posts = await page.evaluate("""
                () => Array.from(document.querySelectorAll('.row-title'))
                    .map(r => r.innerText).slice(0, 5)
            """)
            return posts
        except:
            return []
            
    async def _decide_action(self, pending: list, approved: list, posts: list) -> tuple:
        """Ask LLM what to do"""
        time_in_session = int(time.time() - self.session_start)
        
        pending_text = "\n".join([
            f"{c['number']}. {c['author']}: {c['content'][:60]}..."
            for c in pending
        ]) if pending else "No pending comments"
        
        approved_text = "\n".join([
            f"- {c['author']} on '{c['postTitle']}': {c['content'][:50]}..."
            for c in approved
        ]) if approved else "No approved comments"
        
        posts_text = "\n".join(posts) if posts else "No recent posts"
        
        formatted = self.decision_prompt.format(
            pending_comments=pending_text,
            approved_comments=approved_text,
            recent_posts=posts_text,
            time_in_session=time_in_session,
            num_comments=len(pending),
            num_approved=len(approved)
        )
        
        response = await self.llm.invoke(formatted)
        
        # Parse response
        action = None
        item_number = 0
        
        for line in response.split('\n'):
            if 'ACTION:' in line:
                action_num = line.split(':')[1].strip()
                if '1' in action_num: action = "approve"
                elif '2' in action_num: action = "reject"
                elif '3' in action_num: action = "reply"
                elif '4' in action_num: action = "create_post"
                elif '5' in action_num: action = "end"
            if 'ITEM_NUMBER:' in line:
                try:
                    item_number = int(line.split(':')[1].strip())
                except:
                    item_number = 1
                    
        # Validate
        if item_number < 1 or item_number > len(pending):
            item_number = random.randint(1, len(pending)) if pending else 0
            
        return action, item_number
        
    async def _moderate_comment(self, page: Page, comment_id: str, action_type: str):
        """Approve or spam a comment"""
        self.log(f"{'✓' if action_type == 'approve' else '🚫'} {action_type} comment #{comment_id}")
        
        await page.goto(
            f"{self.config.wp_url}/wp-admin/edit-comments.php?comment_status=moderated",
            wait_until='networkidle'
        )
        await asyncio.sleep(0.5)
        
        row_selector = f'tr#comment-{comment_id}'
        row = await page.query_selector(row_selector)
        
        if not row:
            self.log(f"⚠️ Comment row not found")
            return
            
        await row.hover()
        await asyncio.sleep(0.3)
        
        # Try direct click on action link
        selectors = {
            "approve": f'a[href*="action=approvecomment&c={comment_id}"]',
            "spam": f'a[href*="action=spamcomment&c={comment_id}"]'
        }
        
        element = await page.query_selector(selectors.get(action_type, ""))
        if element:
            await element.click(force=True)
            await page.wait_for_load_state('networkidle')
            if action_type == "approve":
                self.comments_approved += 1
            else:
                self.comments_rejected += 1
                
    async def _reply_to_comment(self, page: Page, comment: dict):
        """Reply to an approved comment"""
        self.log(f"💬 Replying to {comment['author']}...")
        
        # Generate reply
        formatted = self.reply_prompt.format(
            comment_text=comment['content'],
            post_title=comment['postTitle']
        )
        reply_text = await self.llm.invoke(formatted)
        reply_text = reply_text.strip()
        
        await page.goto(
            f"{self.config.wp_url}/wp-admin/edit-comments.php?comment_status=approved",
            wait_until='networkidle'
        )
        await asyncio.sleep(0.5)
        
        row_selector = f'tr#comment-{comment["id"]}'
        row = await page.query_selector(row_selector)
        
        if not row:
            self.log(f"⚠️ Comment row not found")
            return
            
        await row.hover()
        await asyncio.sleep(0.5)
        
        # Click reply button
        reply_btn = await page.query_selector(f'{row_selector} button.vim-r')
        if not reply_btn:
            reply_btn = await page.query_selector(f'button[data-comment-id="{comment["id"]}"][data-action="replyto"]')
            
        if reply_btn:
            await reply_btn.click()
            await asyncio.sleep(1)
            
            reply_textarea = await page.wait_for_selector('#replycontent', timeout=5000)
            if reply_textarea:
                await reply_textarea.fill(reply_text)
                submit_btn = await page.query_selector('#replybtn')
                if submit_btn:
                    await submit_btn.click()
                    await asyncio.sleep(2)
                    self.comments_replied += 1
                    self.log(f"✓ Reply posted")
                    
    async def _create_post(self, page: Page):
        """Create a new blog post with generated image"""
        self.log("📝 Creating post...")
        
        # Get existing topics
        posts = await self._get_recent_posts(page)
        existing = ', '.join(posts[:3]) if posts else 'None yet'
        
        # Generate content
        formatted = self.post_prompt.format(existing_topics=existing)
        response = await self.llm.invoke(formatted)
        
        # Parse response
        title = "New Blog Post"
        content = ""
        image_type = "header"
        in_content = False
        
        for line in response.split('\n'):
            if line.startswith('TITLE:'):
                title = line.replace('TITLE:', '').strip()
                in_content = False
            elif line.startswith('IMAGE_TYPE:'):
                image_type = line.replace('IMAGE_TYPE:', '').strip().lower()
                in_content = False
            elif line.startswith('CONTENT:'):
                content = line.replace('CONTENT:', '').strip()
                in_content = True
            elif line.startswith('TOPIC:'):
                in_content = False
            elif in_content:
                content += '\n' + line
                
        content_plain = re.sub(r'<[^>]+>', '', content).strip()[:3000]
        
        # Generate image based on type
        self.log(f"🎨 Generating {image_type} image...")
        img_bytes = self._generate_image(image_type, title)
        temp_img_path = os.path.join(tempfile.gettempdir(), f'wp_agent_{self.agent_config.agent_id}.png')
        with open(temp_img_path, 'wb') as f:
            f.write(img_bytes)
            
        try:
            await page.goto(
                f"{self.config.wp_url}/wp-admin/post-new.php",
                wait_until='load', timeout=60000
            )
            await asyncio.sleep(3)
            
            # Close any modals (welcome screens, etc)
            await page.keyboard.press('Escape')
            await asyncio.sleep(0.3)
            
            # Check if editor uses iframe (newer WordPress)
            editor_canvas = await page.query_selector('iframe[name="editor-canvas"]')
            if editor_canvas:
                # Editor is in an iframe - get the frame
                editor_frame = await editor_canvas.content_frame()
                if not editor_frame:
                    self.log("⚠️ Could not access editor iframe")
                    return
                    
                # Wait for title input in iframe
                try:
                    await editor_frame.wait_for_selector('[aria-label="Add title"]', timeout=5000)
                    self.log("✓ Editor ready (iframe)")
                except:
                    self.log("⚠️ Editor iframe not ready")
                    return
                
                # Fill title in iframe
                title_elem = await editor_frame.query_selector('[aria-label="Add title"]')
                if title_elem:
                    await title_elem.click()
                    await asyncio.sleep(0.3)
                    await page.keyboard.type(title, delay=20)
                    self.log(f"✓ Title: {title[:40]}...")
                
                await asyncio.sleep(1)
                
                # Fill content - find and click the content area in iframe
                content_selectors = [
                    '[aria-label="Add default block"]',
                    '[aria-label="Empty block; start writing or type forward slash to choose a block"]',
                    'p[data-empty="true"]',
                    '.block-editor-default-block-appender',
                    '[data-type="core/paragraph"]'
                ]
                content_clicked = False
                for sel in content_selectors:
                    content_elem = await editor_frame.query_selector(sel)
                    if content_elem:
                        await content_elem.click()
                        content_clicked = True
                        break
                
                if not content_clicked:
                    # Fallback - try Tab
                    await page.keyboard.press('Tab')
                    
                await asyncio.sleep(0.5)
                # Split into paragraphs and type with Enter between them
                paragraphs = [p.strip() for p in content_plain.split('\n\n') if p.strip()]
                for i, para in enumerate(paragraphs):
                    if len(para) > 300:
                        await page.keyboard.type(para[:100], delay=5)
                        await page.keyboard.insert_text(para[100:])
                    else:
                        await page.keyboard.type(para, delay=3)
                    if i < len(paragraphs) - 1:
                        await page.keyboard.press('Enter')
                        await asyncio.sleep(0.05)
                self.log(f"✓ Content added ({len(content_plain)} chars, {len(paragraphs)} paragraphs)")
            else:
                # Legacy mode - editor not in iframe
                self.log("Using legacy editor mode")
                
                # Wait for Gutenberg editor to load
                for selector in ['.editor-post-title__input', '[aria-label="Add title"]']:
                    try:
                        await page.wait_for_selector(selector, timeout=5000)
                        self.log("✓ Editor ready")
                        break
                    except:
                        continue
                
                # Fill title
                for selector in ['.editor-post-title__input', '[aria-label="Add title"]']:
                    elem = await page.query_selector(selector)
                    if elem:
                        await elem.click()
                        await asyncio.sleep(0.3)
                        await page.keyboard.type(title, delay=20)
                        self.log(f"✓ Title: {title[:40]}...")
                        break
                        
                await asyncio.sleep(1)
                await page.keyboard.press('Tab')
                await asyncio.sleep(0.5)
                paragraphs = [p.strip() for p in content_plain.split('\n\n') if p.strip()]
                for i, para in enumerate(paragraphs):
                    if len(para) > 300:
                        await page.keyboard.type(para[:100], delay=5)
                        await page.keyboard.insert_text(para[100:])
                    else:
                        await page.keyboard.type(para, delay=3)
                    if i < len(paragraphs) - 1:
                        await page.keyboard.press('Enter')
                        await asyncio.sleep(0.05)
                self.log(f"✓ Content added ({len(content_plain)} chars, {len(paragraphs)} paragraphs)")
            
            # Add featured image (optional - don't block on failure)
            await asyncio.sleep(1)
            try:
                # Open settings sidebar if closed
                settings_btn = await page.query_selector('[aria-label="Settings"]')
                if settings_btn:
                    is_pressed = await settings_btn.get_attribute('aria-pressed')
                    if is_pressed != 'true':
                        await settings_btn.click()
                        await asyncio.sleep(0.5)
                    
                # Click on Post tab (not Block tab)
                post_tab = await page.query_selector('[data-tab-id="edit-post/document"]')
                if not post_tab:
                    post_tab = await page.query_selector('button[aria-label="Post"]')
                if not post_tab:
                    post_tab = await page.query_selector('button[data-label="Post"]')
                if post_tab:
                    await post_tab.click()
                    await asyncio.sleep(0.5)
                
                # Scroll sidebar to ensure featured image is visible
                sidebar = await page.query_selector('.interface-complementary-area')
                if sidebar:
                    await sidebar.evaluate('el => el.scrollTop = 500')
                    await asyncio.sleep(0.3)
                    
                # Find and click "Set featured image"
                featured_btn = await page.query_selector('.editor-post-featured-image button')
                if not featured_btn:
                    featured_btn = await page.query_selector('button:has-text("Set featured image")')
                        
                if featured_btn:
                    await featured_btn.click()
                    await asyncio.sleep(2)
                    
                    # Wait for media modal to fully load
                    try:
                        await page.wait_for_selector('.media-modal', timeout=5000)
                    except:
                        self.log("⚠️ Media modal not found")
                    
                    # Click Upload files tab (modal defaults to library view)
                    upload_tab = await page.query_selector('.media-menu-item:has-text("Upload files")')
                    if upload_tab:
                        await upload_tab.click()
                        await asyncio.sleep(1)
                    else:
                        # Try alternate selector
                        tabs = await page.query_selector_all('.media-menu-item')
                        for tab in tabs:
                            text = await tab.text_content()
                            if 'Upload' in text:
                                await tab.click()
                                await asyncio.sleep(1)
                                break
                        
                    # Find file input (should now be visible)
                    file_input = await page.query_selector('input[type="file"]')
                    if file_input:
                        await file_input.set_input_files(temp_img_path)
                        self.log("✓ Image uploaded")
                        await asyncio.sleep(3)  # Wait longer for upload
                        
                        # Select/confirm the image
                        select_btn = await page.query_selector('.media-button-select')
                        if select_btn:
                            await select_btn.click()
                            await asyncio.sleep(1)
                            self.log("✓ Featured image set")
                        else:
                            self.log("⚠️ Select button not found, closing modal")
                            close_btn = await page.query_selector('.media-modal-close')
                            if close_btn:
                                await close_btn.click()
                                await asyncio.sleep(0.5)
                    else:
                        self.log("⚠️ File input not found, closing modal")
                        close_btn = await page.query_selector('.media-modal-close')
                        if close_btn:
                            await close_btn.click()
                            await asyncio.sleep(0.5)
                else:
                    self.log("⚠️ Featured image button not found (skipping)")
            except Exception as e:
                self.log(f"⚠️ Featured image failed: {str(e)[:50]}")
                # Try to close any open modal
                try:
                    close_btn = await page.query_selector('.media-modal-close')
                    if close_btn:
                        await close_btn.click()
                        await asyncio.sleep(0.5)
                except:
                    pass
            
            # Publish the post (simplified - matches working admin agent)
            self.log("📤 Publishing...")
            await asyncio.sleep(1)
            
            # Click publish button (may need two clicks - open panel then confirm)
            publish_btn = await page.query_selector('.editor-post-publish-button__button')
            if not publish_btn:
                publish_btn = await page.query_selector('.editor-post-publish-panel__toggle')
            if not publish_btn:
                publish_btn = await page.query_selector('button:has-text("Publish")')
            
            if publish_btn:
                await publish_btn.click()
                await asyncio.sleep(1)
                
                # Confirm publish (second button in panel)
                confirm_btn = await page.query_selector('.editor-post-publish-button')
                if confirm_btn:
                    await confirm_btn.click()
                    await asyncio.sleep(2)
                
                # Check for success
                success = await page.query_selector('.components-snackbar')
                if success:
                    self.posts_created += 1
                    self.log(f"✓ Post published: {title[:50]}...")
                elif 'post=' in page.url:
                    self.posts_created += 1
                    self.log(f"✓ Post published: {title[:50]}...")
                else:
                    self.log("⚠️ Publish status uncertain")
            else:
                self.log("⚠️ Could not find publish button")
                    
        except Exception as e:
            self.log(f"⚠️ Post creation failed: {e}")
            
    def _generate_header_image(self, text: str) -> bytes:
        """Generate a simple header image with gradient and text"""
        width, height = 1200, 400
        
        color1 = random.choice(['#3498db', '#e74c3c', '#2ecc71', '#f39c12', '#9b59b6'])
        color2 = random.choice(['#1abc9c', '#34495e', '#16a085', '#c0392b', '#8e44ad'])
        
        img = Image.new('RGB', (width, height), color=color1)
        draw = ImageDraw.Draw(img)
        
        # Gradient
        for i in range(height):
            r1, g1, b1 = int(color1[1:3], 16), int(color1[3:5], 16), int(color1[5:7], 16)
            r2, g2, b2 = int(color2[1:3], 16), int(color2[3:5], 16), int(color2[5:7], 16)
            ratio = i / height
            r = int(r1 * (1 - ratio) + r2 * ratio)
            g = int(g1 * (1 - ratio) + g2 * ratio)
            b = int(b1 * (1 - ratio) + b2 * ratio)
            draw.line([(0, i), (width, i)], fill=(r, g, b))
            
        # Text
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 60)
        except:
            font = ImageFont.load_default()
            
        bbox = draw.textbbox((0, 0), text, font=font)
        x = (width - (bbox[2] - bbox[0])) // 2
        y = (height - (bbox[3] - bbox[1])) // 2
        
        draw.text((x+2, y+2), text, font=font, fill='black')
        draw.text((x, y), text, font=font, fill='white')
        
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        return buf.getvalue()
        
    def _generate_chart_image(self, title: str) -> bytes:
        """Generate a bar chart using matplotlib"""
        fig, ax = plt.subplots(figsize=(8, 5))
        
        categories = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun']
        values = [random.randint(20, 100) for _ in range(6)]
        colors = ['#3498db', '#e74c3c', '#2ecc71', '#f39c12', '#9b59b6', '#1abc9c']
        
        ax.bar(categories, values, color=colors[:len(categories)])
        ax.set_title(title, fontsize=14, fontweight='bold')
        ax.set_ylabel('Value', fontsize=10)
        ax.grid(axis='y', alpha=0.3)
        
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=100, bbox_inches='tight')
        buf.seek(0)
        plt.close(fig)
        return buf.getvalue()
        
    def _generate_diagram_image(self) -> bytes:
        """Generate a simple network/flow diagram"""
        width, height = 800, 600
        img = Image.new('RGB', (width, height), color='white')
        draw = ImageDraw.Draw(img)
        
        colors = ['#3498db', '#e74c3c', '#2ecc71', '#f39c12']
        
        # Draw connected boxes
        for i in range(4):
            x = 150 + (i % 2) * 400
            y = 150 + (i // 2) * 300
            draw.rectangle([x, y, x+150, y+100], outline=colors[i], fill=colors[i], width=3)
            
            # Connecting lines
            if i < 2:
                draw.line([x+75, y+100, x+75, y+150], fill='gray', width=2)
                
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        return buf.getvalue()
        
    def _generate_image(self, image_type: str, title: str) -> bytes:
        """Generate an image based on type"""
        if image_type == 'chart':
            return self._generate_chart_image(title)
        elif image_type == 'diagram':
            return self._generate_diagram_image()
        else:
            return self._generate_header_image(title[:30])


# =============================================================================
# Orchestrator
# =============================================================================

class AgentOrchestrator:
    """Manages all agents"""
    
    def __init__(self, config: Config):
        self.config = config
        self.browser_manager = BrowserManager(config)
        self.llm_client = LLMClient(config)
        self.agent_configs: List[AgentConfig] = []
        self.agents: List[BaseAgent] = []
        
    def _assign_browser_types(self) -> List[BrowserType]:
        """Assign browser types based on distribution"""
        total = self.config.num_users + self.config.num_admins
        
        num_chrome = int(total * self.config.browser_chrome_pct)
        num_webkit = int(total * self.config.browser_webkit_pct)
        num_firefox = total - num_chrome - num_webkit
        
        browsers = (
            ["chromium"] * num_chrome +
            ["webkit"] * num_webkit +
            ["firefox"] * max(1, num_firefox)
        )
        
        random.shuffle(browsers)
        return browsers[:total]
        
    def _create_agent_configs(self) -> List[AgentConfig]:
        """Create configuration for all agents"""
        configs = []
        browser_types = self._assign_browser_types()
        
        total = self.config.num_users + self.config.num_admins
        
        for i in range(total):
            is_admin = i < self.config.num_admins
            agent_type = "admin" if is_admin else "user"
            agent_id = f"admin_{i+1}" if is_admin else f"user_{i+1-self.config.num_admins}"
            
            proxy_port = None
            if self.config.proxy_enabled:
                proxy_port = self.config.proxy_base_port + i
                
            configs.append(AgentConfig(
                agent_id=agent_id,
                agent_type=agent_type,
                browser_type=browser_types[i],
                proxy_port=proxy_port
            ))
            
        return configs
        
    async def run(self):
        """Start all agents"""
        print(f"\n{'='*60}")
        print(f"WordPress Traffic Generator")
        print(f"  Users: {self.config.num_users}")
        print(f"  Admins: {self.config.num_admins}")
        print(f"  Proxy: {'Enabled' if self.config.proxy_enabled else 'Disabled'}")
        print(f"  LLM: {self.config.ollama_host}")
        print(f"{'='*60}\n")
        
        # Initialize
        await self.browser_manager.start()
        self.agent_configs = self._create_agent_configs()
        
        # Print agent assignment
        print("Agent Configuration:")
        for cfg in self.agent_configs:
            proxy_info = f", proxy:{cfg.proxy_port}" if cfg.proxy_port else ""
            print(f"  {cfg.agent_id}: {cfg.browser_type}{proxy_info}")
        print()
        
        # Create agent tasks with staggered starts
        tasks = []
        for cfg in self.agent_configs:
            if cfg.agent_type == "admin":
                agent = AdminAgent(cfg, self.config, self.browser_manager, self.llm_client)
            else:
                agent = UserAgent(cfg, self.config, self.browser_manager, self.llm_client)
                
            self.agents.append(agent)
            
        # Start agents with stagger
        async def start_agent(agent: BaseAgent, delay: float):
            await asyncio.sleep(delay)
            await agent.run()
            
        delay = 0
        for agent in self.agents:
            tasks.append(asyncio.create_task(start_agent(agent, delay)))
            delay += random.uniform(self.config.stagger_min, self.config.stagger_max)
            
        print(f"🚀 Starting {len(tasks)} agents with staggered launch...\n")
        
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            print("\n⚠️ Agents cancelled")
        finally:
            await self.browser_manager.stop()
            
        # Summary
        print(f"\n{'='*60}")
        print("Session Summary:")
        total_comments = sum(a.comments_made for a in self.agents if isinstance(a, UserAgent))
        total_approved = sum(a.comments_approved for a in self.agents if isinstance(a, AdminAgent))
        total_posts = sum(a.posts_created for a in self.agents if isinstance(a, AdminAgent))
        print(f"  User comments: {total_comments}")
        print(f"  Admin approved: {total_approved}")
        print(f"  Posts created: {total_posts}")
        print(f"{'='*60}\n")


# =============================================================================
# Main
# =============================================================================

async def main():
    config = Config()
    
    # For testing, use smaller numbers
    # config.num_users = 2
    # config.num_admins = 1
    
    orchestrator = AgentOrchestrator(config)
    await orchestrator.run()


if __name__ == "__main__":
    asyncio.run(main())
