import requests, plextmdb, os, sys, zipfile, codecs
from urlparse import urljoin
from bs4 import BeautifulSoup
from cStringIO import StringIO


def get_subtitles_yts( title ):
    tmdbid = plextmdb.get_movie_tmdbids( title )
    if tmdbid is None:
        return None
    imdbid = plextmdb.get_imdbid_from_id( int( tmdbid ) )
    if imdbid is None:
        return None
    #
    ## now get the main page for the YTS subtitles
    ## code inspired by https://github.com/kartouch/yts/blob/master/lib/yts.rb
    response = requests.get('http://www.yifysubtitles.com/movie-imdb/%s' % imdbid )
    if response.status_code != 200:
        return None
    html = BeautifulSoup( response.content, 'lxml' )
    def is_english_subtitle( elem ):
        if 'data-id' not in elem.attrs:
            return False
        #
        ## language elem
        lang_elems = filter(lambda elm: 'class' in elm.attrs and max(elm.attrs['class']) == 'sub-lang', elem.find_all('span'))
        if len( lang_elems ) != 1:
            return False
        lang_elem = max( lang_elems )
        language = lang_elem.get_text( ).lower( )
        return language == 'english'

    valid_st_elems = filter( is_english_subtitle, html.find_all('tr') )
    if len( valid_st_elems ) == 0:
        return None
    valid_subs = [ ]
    for subtitle_elem in valid_st_elems:
        first_href = filter(lambda elm: elm.text.strip().startswith('subtitle'), subtitle_elem.find_all('a'))
        if len( first_href ) != 1:
            continue
        first_href = max( first_href )
        name = ' '.join( first_href.text.strip( ).split( )[1:] )
        last_href = filter(lambda elm: 'class' in elm.attrs and max(elm.attrs['class']) == 'subtitle-download',
                           subtitle_elem.find_all('a'))
        if len( last_href ) != 1:
            continue
        last_href = max( last_href )
        pageurl = urljoin( 'http://www.yifysubtitles.com', last_href.attrs['href'] )
        resp2 = requests.get( pageurl )
        if resp2.status_code != 200:
            continue
        html2 = BeautifulSoup( resp2.content, 'lxml' )
        button_elem = filter(lambda elm: 'href' in elm.attrs and elm.attrs['href'].endswith('.zip'), html2.find_all('a'))
        if len( button_elem ) != 1:
            continue
        button_elem = max( button_elem )
        url = button_elem.attrs['href']
        if not url.endswith('zip'):
            continue
        valid_subs.append({ 'name' : name, 'url' : url })
    if len( valid_subs ) == 0:
        return None
    return valid_subs

def download_yts_sub( url, srtfilename = 'eng.srt' ):
    assert( srtfilename.endswith( '.srt' ) )
    assert( url.endswith( '.zip' ) )
    response = requests.get( url )
    if response.status_code != 200:
        raise ValueError("Error, could not download %s." % url )
    with zipfile.ZipFile( StringIO( response.content ), 'r' ) as zf:
        name = max( zf.namelist( ) )
        if not name.endswith('.srt'):
            raise ValueError("Error, name = %s does not end with srt." % name )
        #with codecs.open( srtfilename, 'w', 'utf-8' ) as openfile:
        with open( srtfilename, 'w') as openfile:
            openfile.write( zf.read( name ) )