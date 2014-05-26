#!/usr/bin/env python2

import requests
import gevent
from BeautifulSoup import BeautifulSoup
import lxml.html
import sys
import argparse
from random import randrange
from urlparse import urlparse


clean_links_with_www = None
clean_links_without_www = None

def parse_args():
    '''
    Create arguments
    '''
    parser = argparse.ArgumentParser()
    parser.add_argument("-u", "--url", help="The seed URL to start crawling")
    parser.add_argument("-p", "--parallel", default=500, help="Specifies how many pages you want to crawl in parallel. Default = 500")
    return parser.parse_args()

class Crawler:

    def __init__(self, base_url):
        self.depth = 0
        self.concurrency = 500
        self.scanned_links = []

        # Fetch the user supplied URL, follow redirects, then return the new real seed url
        #self.seed_url = self.get_seed_url(base_url)
        self.seed_url = base_url
        self.hostname = self.seed_url_processor()[0]
        print 'hostname: ', self.hostname
        self.protocol = self.seed_url_processor()[1]
        print 'proto: ', self.protocol
        self.root_domain = self.seed_url_processor()[2]
        print 'root_domain: ', self.root_domain

        self.run(self.seed_url)

    def get_seed_url(self, base_url):
        '''
        Get the url in case of redirection given the user input like http://cnn.com to http://www.cnn.com
        '''
        seed_resp = requests.get(base_url, headers = {'User-Agent':self.get_user_agents()})
        seed_url = seed_resp.url
        return seed_url

    def run(self, url):
        global clean_links_without_www, clean_links_with_www
        html = self.get_html(url)
        raw_links = self.get_raw_links(html)
        cleaned_links = self.clean_links(raw_links)

        if 'www' in self.seed_url:
            clean_links_with_www = cleaned_links
        else:
            clean_links_without_www = cleaned_links
        for l in cleaned_links:
        #    print l
            pass
        print 'Number of links:', len(cleaned_links)

    def get_html(self, u):
        '''
        Get page HTML (does not include JS injected html)
        Randomizes the user-agent amongst the top 6 most common as of 2014
        Maybe replace this with a webkit-driven headless browser to get the DOM?
        '''
        resp = requests.get(u, headers = {'User-Agent':self.get_user_agents()})
        html = resp.text
        return html

    def get_raw_links(self, html):
        '''
        Finds all links on the page
        lxml is faster than BeautifulSoup
        '''
        root = lxml.html.fromstring(html)
        raw_links = [link[2] for link in root.iterlinks()] #if 'string' in link
        # Alternative method, but I found it gets just a few less links
        #links = root.xpath('//a/@href')
        return raw_links

    def clean_links(self, links):
        '''
        Assemble the scraped links into working URLs
        All the valid links tend to start with #, /, javascript:, or http
        '''
        cleaned_links = []
        for link in links:
            link = link.strip()
            if len(link) > 0:
                if '/' == link[0]:
                    link = self.protocol+self.hostname+link
                    cleaned_links.append(link)
                # Don't add links that start with # since they're just JS or an anchor
                elif '#' == link[0]:
                    continue
                # Handle links to outside domains
                elif 'http' == link[:4].lower():
                    # urlsplit is the protocol + hostname
                    urlsplit = '/'.join(link.split('/')[0:3])
                    if self.root_domain in urlsplit:
                        cleaned_links.append(link)
                    else:
                        continue
                # Ignore javascript:... links
                elif 'javascript:' in link:
                    continue

                else:
                    print '###############LINK:', link
                    link = self.protocol+self.hostname+'/'+link
                    print '###############BLINDLY FIXED LINK:', link
                    cleaned_links.append(link)

        cleaned_links = list(set(cleaned_links))
        #cleaned_links = self.get_inscope_links(cleaned_links)
        return cleaned_links

    def seed_url_processor(self):
        '''
        Get the seed url domain, protocol, and hostname using urlparse
        '''
        try:
            parsed_url = urlparse(self.seed_url)
            # Get the protocol
            protocol = parsed_url.scheme+'://'
            # Get the hostname (includes subdomains)
            hostname = parsed_url.hostname
            # Get root domain
            root_domain = '.'.join(hostname.split('.')[-2:])
        except:
            sys.exit('[-] Enter a valid URL that starts with "http://" or "https://", example: http://danmcinerney.org')

        return (hostname, protocol, root_domain)

    def get_user_agents(self):
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

C = Crawler(parse_args().url)

#C = Crawler('http://www.cnn.com')
#print C.seed_url
#print ''
#
#for u in list(set(clean_links_without_www)-set(clean_links_with_www)):
#    print u
#    pass

# Without www, cnn.com gets like 60 more links compared to www.cnn.com as the seed url. Why? Redirect have something to do with it?
# Answer: the get_inscope_links() was checking if self.protocol and self.hostname were in the link to filter out of scope links, but that work was already being done in clean_links()


#    def get_inscope_links(self, cleaned_links):
#        '''
#        Make the list of links only reflect subdoains and URLs of the original domain
#        '''
#        in_scope_links = []
#        for link in cleaned_links:
#            if self.protocol in link and self.root_domain in link:
#                in_scope_links.append(link)
#        return in_scope_links

