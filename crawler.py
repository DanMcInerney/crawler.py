#!/usr/bin/env python2

import gevent.monkey
gevent.monkey.patch_all()

import logging
import gevent.pool
import gevent.queue
import urllib
import time
import requests
import gevent
from BeautifulSoup import UnicodeDammit
import lxml.html
import sys
import argparse
from random import randrange
from urlparse import urlparse
import socket
socket.setdefaulttimeout(30)


def parse_args():
    '''
    Create arguments
    '''
    parser = argparse.ArgumentParser()
    parser.add_argument("-u", "--url", help="The seed URL to scheduler crawling")
    parser.add_argument("-p", "--parallel", default=500, help="Specifies how many pages you want to crawl in parallel. Default = 500")
    parser.add_argument("-d", "--depth", default=1, help="Specifies how many levels deep you want to crawl")
    return parser.parse_args()

class Crawler:

    def __init__(self, args):

        # Set up the logging
        #logging.basicConfig(level=logging.DEBUG)
        logging.basicConfig(level=None)
        self.logger = logging.getLogger(__name__)
        self.handler = logging.FileHandler('crawler.log', 'a')
        self.handler.setLevel(logging.DEBUG)
        self.logger.addHandler(self.handler)

        self.end_depth = int(args.depth) # How many pages deep we want to crawl
        self.cur_depth = 0 # Depth crawler has reached so far
        self.parallel = int(args.parallel) # How many net conns to make in parallel
        self.net_pool = gevent.pool.Pool(self.parallel) # Create pool to fill with net conn workers
        self.data_pool = gevent.pool.Pool(100) # Create pool to fill with html processor workers
        self.net_q = gevent.queue.Queue() # Create queue from which each worker will draw a job (net conn)
        self.data_q = gevent.queue.Queue() # Place data from finished net conn here to get processed
        self.links_found = [] # Non-duplicate links found within the current depth level
        self.base_url = args.url
        self.all_links = {} # All links found both crawled and uncrawled organized by depth
        print 'base url: ', args.url

        # Add the seed link to the list that gets put in the queue and add it to all_links
        self.run()

    def run(self):
        '''
        Make sure there's a base url, put it in the queue, then start the scheduler
        '''
        if not self.base_url:
            sys.exit('[-] Enter valid URL after the -u option')

        # Set up all_links
        for x in xrange(1, self.end_depth+2):
            self.all_links[x] = []
        self.all_links[1] = [self.base_url] # All links found both crawled and uncrawled organized by depth
        self.scheduler()

    def scheduler(self):
        '''
        Adds new links to the network connection queue or increments the depth level if no new
        links and data processing completed
        '''
        self.cur_depth += 1
        print '\n[*] Crawler depth:', self.cur_depth
        print '---------------------'

        # Make sure we don't double add the seed url
        #if self.cur_depth != 0:
        for url in self.all_links[self.cur_depth]:
            self.net_q.put(url)

        if not self.net_q.empty():
            # Create network connections
            self.create_net_conns()

        # While the net connections are being made, process whatever html has already come in
        while 1:
            if not self.data_q.empty():
                for x in xrange(0, min(self.data_q.qsize(), 99)):
                    self.data_pool.spawn(self.html_processor)
            if self.net_pool.free_count() != self.net_pool.size:
                try:
                    gevent.sleep(1)
                except KeyboardInterrupt:
                    self.shutdown()
            else:
                self.data_pool.join()
                break

        if len(self.all_links[self.cur_depth+1]) == 0:
            self.logger.info('No links in next depth level. Current depth: %d' % self.cur_depth)
            sys.exit('[-] No more unique links found. Current depth: %d' % self.cur_depth)
        elif self.cur_depth < self.end_depth:
            self.scheduler()
        else:
            total = self.total_links()
            print 'Total links:', total
            sys.exit('\n[-] Hit max depth: %d' % self.cur_depth)

    def total_links(self):
        '''
        Get the total amount of unique links found so far
        '''
        total = 0
        for x in xrange(1,self.cur_depth+2):
            total = total + len(self.all_links[x])
        return total

    def create_net_conns(self):
        '''
        Spawn the network connections
        '''
        try:
            for x in xrange(0, self.net_q.qsize()):
                self.net_pool.spawn(self.net_conn)#.join(timeout=30)
        except KeyboardInterrupt:
            self.shutdown()

    def net_conn(self):
        '''
        Fetchs the links on a page, creates a clean list of them
        '''
        try:
            url = self.net_q.get()
            resp = requests.get(url, headers = {'User-Agent':self.get_user_agent()})
            html = resp.content
            if '/' == resp.url[:-1]:
                post_redirect_url = resp.url[:-1] # this gets the url in case of redirect and strips the last '/'
            else:
                post_redirect_url = resp.url
        except Exception as e:
            print '[!] Error: %s\n          ' % url, e
            return

        self.data_q.put((html, post_redirect_url))

    def html_processor(self):
        '''
        Parse the HTML and convert the links to usable URLs
        '''
        html, url = self.data_q.get()

        # Check if this is the seed URL
        if self.cur_depth == 1:
            self.hostname, self.protocol, self.root_domain = self.url_processor(url)
            hostname = self.hostname
            protocol = self.protocol
        else:
            hostname, protocol, root_domain = self.url_processor(url)

        raw_links = self.get_raw_links(html, url)
        if raw_links == None:
            return
        cleaned_links = self.clean_links(raw_links, url, hostname, protocol)

        # De-duplicate
        unique_links = []
        unique_link = None
        for l in cleaned_links:
            unique_link = self.get_unique_links(l)
            if unique_link:
                unique_links.append(unique_link)

        self.all_links[self.cur_depth+1] = self.all_links[self.cur_depth+1] + unique_links
        print url+':', len(cleaned_links), len(unique_links)

    def get_raw_links(self, html, url):
        '''
        Finds all links on the page
        lxml is faster than BeautifulSoup
        '''
        try:
            root = lxml.html.fromstring(html)
        except Exception:
            self.logger.error('[!] Failed to parse the html from %s' % url)
            return

        raw_links = [link[2] for link in root.iterlinks()] #if 'string' in link
        #for x in raw_links:
         #   print x
        # Alternative method, but I found it gets just a few less links
        #links = root.xpath('//a/@href')
        return raw_links

    def clean_links(self, links, url, hostname, protocol):
        '''
        Assemble the scraped links into working URLs
        Cleans out all the links that won't house links themselves, like images
        '''
        cleaned_links = []
        parent_hostname = protocol+hostname
        link_exts = ['.ogg', '.flv', '.swf', '.mp3', '.jpg', '.jpeg', '.gif', '.css', '.ico', '.rss' '.tiff', '.png', '.pdf']

        for link in links:
            link = self.filter_links(link, link_exts, parent_hostname)
            if link:
                cleaned_links.append(link)

        # Only include links we haven't already found
        #cleaned_links = list(set([l for l in cleaned_links if l not in self.all_links]))
        cleaned_links = list(set(cleaned_links))
        return cleaned_links

    def filter_links(self, link, link_exts, parent_hostname):
        link = link.strip()
        link = urllib.unquote(link)
        if len(link) > 0:
            # Filter out pages that aren't going to have links on them. Hacky.
            for ext in link_exts:
                if ext in link[-4:]:
                    self.logger.debug('- Filtered: '+link)
                    return
            # Don't add links to scheduler with # since they're just JS or an anchor
            if '#' == link[0]:
                self.logger.debug('- Filtered: '+link)
                return
            # Handle links like /articles/hello.html
            elif '/' == link[0]:
                link = parent_hostname+link.decode('utf-8')
                self.logger.debug('+ Appended: '+link)
                return link
            # Ignore links that are simple "http://"
            elif 'http://' == link.lower():
                self.logger.debug('- Filtered: '+link)
                return
            # Handle full URL links
            elif 'http' == link[:4].lower():
                link_hostname = urlparse(link).hostname
                if not link_hostname:
                    self.logger.error('Failed to get the hostname from this link: %s' % link)
                    return
                if self.root_domain in link_hostname:
                    self.logger.debug('+ Appended: '+link)
                    return link
            # Ignore links that don't scheduler with http but still have : like android-app://com.tumblr
            # or javascript:something
            elif ':' in link:
                self.logger.debug('- Filtered: '+link)
                return
            # Catch all unhandled URLs like "about/me.html" will go here
            else:
                link = parent_hostname+'/'+link
                self.logger.debug('+ Appended: '+link)
                return link

    def get_unique_links(self, link):
        '''
        Compared the links found on a page to all the links crawled so far to prevent duplicates
        '''
        # +1 to check uncrawled links, and +1 because xrange is xrange(x) goes from 0 to x-1
        for depth in xrange(1,self.cur_depth+2):
            if link in self.all_links[depth]:
               return None
        return link

    def url_processor(self, url):
        '''
        Get the url domain, protocol, and hostname using urlparse
        '''
        try:
            parsed_url = urlparse(url)
            # Get the protocol
            protocol = parsed_url.scheme+'://'
            # Get the hostname (includes subdomains)
            hostname = parsed_url.hostname
            # Get root domain
            root_domain = '.'.join(hostname.split('.')[-2:])
        except:
            print '[-] Could not parse url:', url

        return (hostname, protocol, root_domain)

    def get_user_agent(self):
        '''
        Set the UA to be a random 1 of the top 6 most common
        '''
        user_agents = ['Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/34.0.1847.131 Safari/537.36',
                       'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_9_2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/34.0.1847.131 Safari/537.36',
                       'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_9_2) AppleWebKit/537.75.14 (KHTML, like Gecko) Version/7.0.3 Safari/537.75.14',
                       'Mozilla/5.0 (Windows NT 6.1; WOW64; rv:29.0) Gecko/20100101 Firefox/29.0',
                       'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/34.0.1847.137 Safari/537.36',
                       'Mozilla/5.0 (Windows NT 6.1; WOW64; rv:28.0) Gecko/20100101 Firefox/28.0']
        user_agent = user_agents[randrange(5)]
        return user_agent

    def shutdown(self):
        '''
        Shutdown functions
        '''
        total = self.total_links()
        print '[+] All unique links found on *.%s: %d' % ('.'.join(self.hostname.split('.')[-2:]), total)
        sys.exit('[*] Finished')

C = Crawler(parse_args())
