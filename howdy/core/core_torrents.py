import requests, re, threading, cfscrape
import os, time, numpy, logging, datetime, pickle, gzip
from itertools import chain
from requests.compat import urljoin
from multiprocessing import Process, Manager
from pathos.multiprocessing import Pool
from bs4 import BeautifulSoup
#
from howdy.core import core_deluge, get_formatted_size, get_maximum_matchval, return_error_raw, core

def get_book_torrent_jackett( name, maxnum = 10, keywords = [ ], verify = True ):
    """
    Returns a :py:class:`tuple` of candidate book Magnet links found using the main Jackett_ torrent searching service and the string ``"SUCCESS"``, if successful.

    :param str name: the book to search for.
    :param int maxnum: optional argumeent, the maximum number of magnet links to return. Default is 10. Must be :math:`\ge 5`.
    :param list keywords: optional argument. If not empty, the title of the candidate element must have at least one of the keywords in ``keywords``.
    :param bool verify:  optional argument, whether to verify SSL connections. Default is ``True``.
    
    :returns: if successful, then returns a two member :py:class:`tuple` the first member is a :py:class:`list` of elements that match the searched episode, ordered from *most* seeds and leechers to least. The second element is the string ``"SUCCESS"``. The keys in each element of the list are,
       
      * ``title`` is the name of the candidate book to download, and in parentheses the size of the candidate in MB or GB.
      * ``rawtitle`` also the name of the candidate episode to download.
      * ``seeders`` is the number of seeds for this Magnet link.
      * ``leechers`` is the number of leeches for this Magnet link.
      * ``link`` is the Magnet URI link.
      * ``torrent_size`` is the size of this torrent in Megabytes.
    
    If this is unsuccessful, then returns an error :py:class:`tuple` of the form returned by :py:meth:`return_error_raw <howdy.core.return_error_raw>`.
    
    :rtype: tuple

    .. _Jackett: https://github.com/Jackett/Jackett
    """
    import validators
    assert( maxnum >= 5 )
    data = core.get_jackett_credentials( )
    if data is None:
        return return_error_raw('FAILURE, COULD NOT GET JACKETT SERVER CREDENTIALS')
    url, apikey = data
    if not url.endswith( '/' ): url = '%s/' % url
    endpoint = 'api/v2.0/indexers/all/results/torznab/api'
    name_split = name.split()
    last_tok = name_split[-1].lower( )
    status = re.match('^s[0-9]{2}e[0-9]{2}',
                      last_tok )
    
    def _return_params( name ):
        params = { 'apikey' : apikey, 'q' : name, 'cat' : '7020' }
        return params

    logging.info( 'URL ENDPOINT: %s, PARAMS = %s.' % (
        urljoin( url, endpoint ), { 'apikey' : apikey, 'q' : name, 'cat' : '7020' } ) )
    response = requests.get(
        urljoin( url, endpoint ),
        params = { 'apikey' : apikey, 'q' : name, 'cat' : '7020' },
        verify = verify ) # tv shows
    if response.status_code != 200:
        return return_error_raw( 'FAILURE, PROBLEM WITH JACKETT SERVER ACCESSIBLE AT %s.' % url )
    html = BeautifulSoup( response.content, 'lxml' )
    if len( html.find_all('item') ) == 0:
        return return_error_raw( 'FAILURE, NO BOOKS SATISFYING CRITERIA FOR GETTING %s' % name )
    items = [ ]
    
    def _get_magnet_url( item ):
        magnet_url = item.find( 'torznab:attr', { 'name' : 'magneturl' } )
        if magnet_url is not None and 'magnet' in magnet_url['value']:
            return magnet_url['value']
        #
        ## not found it here, must go into URL
        url2 = item.find('guid')
        if url2 is None: return None
        url2 = url2.text
        if not validators.url( url2 ): return None
        resp2 = requests.get( url2, verify = verify )
        if resp2.status_code != 200: return None
        h2 = BeautifulSoup( resp2.content, 'lxml' )
        valid_magnet_links = set(map(lambda elem: elem['href'],
                                     filter(lambda elem: 'href' in elem.attrs and 'magnet' in elem['href'],
                                            h2.find_all('a'))))
        if len( valid_magnet_links ) == 0: return None
        return max( valid_magnet_links )

    if status is None: last_tok = None
    for item in html('item'):
        title = item.find('title')
        if title is None: continue
        title = title.text
        #
        ## now check if the sXXeYY in name
        if last_tok is not None:
            if last_tok not in title.lower( ): continue
        torrent_size = item.find('size')
        if torrent_size is not None:
            torrent_size = float( torrent_size.text ) / 1024**2
        seeders = item.find( 'torznab:attr', { 'name' : 'seeders' } )
        if seeders is None: seeders = -1
        else: seeders = int( seeders[ 'value' ] )
        leechers = item.find( 'torznab:attr', { 'name' : 'peers' } )
        if leechers is None: leechers = -1
        else: leechers = int( leechers[ 'value' ] )
        #
        ## now do one of two things to get the magnet URL
        magnet_url = _get_magnet_url( item )
        if magnet_url is None: continue
        myitem = { 'title' : title,
                   'rawtitle' : title,
                   'seeders' : seeders,
                   'leechers' : leechers,
                   'link' : magnet_url }
        if torrent_size is not None:
            myitem[ 'title' ] = '%s (%0.1f MiB)' % ( title, torrent_size )
            myitem[ 'torrent_size' ] = torrent_size
        pubdate_elem = item.find( 'pubdate' )
        if pubdate_elem is not None:
            try:
                pubdate_s = pubdate_elem.get_text( ).split(',')[-1].strip( )
                pubdate_s = ' '.join( pubdate_s.split()[:3] )
                pubdate = datetime.datetime.strptime(
                    pubdate_s, '%d %B %Y' ).date( )
                myitem[ 'pubdate' ] = pubdate
            except: pass
        items.append( myitem )

    items = sorted(items, key = lambda elem: elem['seeders'] + elem['leechers' ] )[::-1]
    if len( keywords ) != 0:
        items = list(filter(lambda item: any(map(lambda tok: tok.lower( ) in item['rawtitle'].lower( ), keywords ) ) and
                            not any(map(lambda tok: tok.lower( ) in item['rawtitle'].lower( ), keywords_exc ) ) and
                            all(map(lambda tok: tok.lower( ) in item['rawtitle'].lower( ), must_have ) ),
                            items ) )
    if len( items ) == 0:
        return return_error_raw( 'FAILURE, NO BOOKS SATISFYING CRITERIA FOR GETTING %s' % name )
        
    return items[:maxnum], 'SUCCESS'
