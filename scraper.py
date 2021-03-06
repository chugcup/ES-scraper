#!/usr/bin/env python

import argparse
import difflib
import Image
import imghdr
import os
import re
import readline
import sys
import unicodedata
import urllib
import urllib2
from xml.etree import ElementTree as ET
from xml.etree.ElementTree import Element, SubElement
import zlib

SCUMMVM = False

parser = argparse.ArgumentParser(description='ES-scraper, a scraper for EmulationStation')
parser.add_argument("-w", metavar="pixels", help="defines a maximum width (in pixels) for boxarts (anything above that will be resized to that value)", type=int)
parser.add_argument("-t", metavar="pixels", help="defines a maximum height (in pixels) for boxarts (anything above that will be resized to that value)", type=int)
parser.add_argument("-pisize", help="use best Raspberry Pi dimensions (375 x 350) for boxarts", action='store_true')
parser.add_argument("-noimg", help="disables boxart downloading", action='store_true')
parser.add_argument("-v", help="verbose output", action='store_true')
parser.add_argument("-f", help="force re-scraping (ignores and overwrites the current gamelist)", action='store_true')
parser.add_argument("-crc", help="CRC scraping", action='store_true')
parser.add_argument("-p", help="partial scraping (per console)", action='store_true')
parser.add_argument("-l", help="i'm feeling lucky (use first result)", action='store_true')
parser.add_argument('-newpath', help="gamelist & boxart are written in $HOME/.emulationstation/%%NAME%%/", action='store_true')
parser.add_argument('-fix', help="temporary thegamesdb missing platform fix", action='store_true')
args = parser.parse_args()

# URLs for retrieving from TheGamesDB API
GAMESDB_BASE  = "http://thegamesdb.net/api/"
PLATFORM_URL  = GAMESDB_BASE + "GetPlatform.php"
GAMEINFO_URL  = GAMESDB_BASE + "GetGame.php"
GAMESLIST_URL = GAMESDB_BASE + "GetGamesList.php"

DEFAULT_WIDTH  = 375
DEFAULT_HEIGHT = 350

# Used to signal user wants to manually define title from results
class ManualTitleInterrupt(Exception):
    pass

def normalize(s):
   return ''.join((c for c in unicodedata.normalize('NFKD', unicode(s)) if unicodedata.category(c) != 'Mn'))

def fixExtension(file):
    newfile = "%s.%s" % (os.path.splitext(file)[0],imghdr.what(file))
    os.rename(file, newfile)
    return newfile

def readConfig(file):
    lines = config.read().splitlines()
    systems = []
    for line in lines:
        if not line.strip() or line[0]=='#':
            continue
        else:
            if "NAME=" in line:
                name = line.split('=')[1]
            if "PATH=" in line:
                path = line.split('=')[1]
            elif "EXTENSION" in line:
                ext = line.split('=')[1]
            elif "PLATFORMID" in line:
                pid = line.split('=')[1]
                if not pid:
                    continue
                else:
                    system = (name,path,ext,pid)
                    systems.append(system)
    config.close()
    return systems

def crc(fileName):
    prev = 0
    for eachLine in open(fileName,"rb"):
        prev = zlib.crc32(eachLine, prev)
    return "%X" % (prev & 0xFFFFFFFF)

def indent(elem, level=0):
    i = "\n" + level*"  "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + "  "
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
        for elem in elem:
            indent(elem, level+1)
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = i

def getPlatformName(id):
    req = urllib2.Request(PLATFORM_URL, urllib.urlencode({'id': id}),
                          headers={'User-Agent' : "RetroPie Scraper Browser"})
    data = urllib2.urlopen( req )
    platform_data = ET.parse(data)
    return platform_data.find('Platform/Platform').text

def exportList(gamelist):
    if gamelistExists and args.f is False:
        for game in gamelist.iter("game"):
            existinglist.getroot().append(game)

        indent(existinglist.getroot())
        ET.ElementTree(existinglist.getroot()).write("gamelist.xml")
        print "Done! %s updated." % os.getcwd()+"/gamelist.xml"
    else:
        indent(gamelist)
        ET.ElementTree(gamelist).write("gamelist.xml")
        print "Done! List saved on %s" % os.getcwd()+"/gamelist.xml"

def getFiles(base):
    dict = set([])
    for files in sorted(os.listdir(base)):
        if files.endswith(tuple(ES_systems[var][2].split(' '))):
            filepath = os.path.abspath(os.path.join(base, files))
            dict.add(filepath)
    return dict

def getPlatformGameList(platformID):
    platform = getPlatformName(platformID)
    gamelist = urllib2.Request(GAMESLIST_URL, urllib.urlencode({'platform' : platform}),
                               headers={'User-Agent' : "RetroPie Scraper Browser"})
    return ET.parse(urllib2.urlopen(gamelist)).getroot()

def getGameInfo(file, platformID, gamelist):
    title = re.sub(r'\[.*?\]|\(.*?\)', '', os.path.splitext(os.path.basename(file))[0]).strip()
    results = gamelist.findall('Game')
    options = []

    def stripRegionStrings(title):
        # Strip out parens matching certain strings
        #  e.g.  (Rev 1), (World), (USA, Japan)
        region_match = '^\((?:Rev|USA|Japan|France|Europe|World|En,)'
        parens = re.findall('(\(.*?\))', title)
        for p in parens:
            if re.match(region_match, p) is not None:
                title = title.replace(' %s' % p, '')
        return title

    def getTitleOptions(title, results):
        options = []
        ch_exclude = set(',:&!')
        common_words = ['in','of','the','and','to','a','-']

        scrubbed_title = stripRegionStrings(title)
        scrubbed_title = ''.join(ch for ch in scrubbed_title if ch not in ch_exclude)

        word_list = filter(lambda x: x.lower() not in common_words \
                              and len(x) > 2, scrubbed_title.split() )

        for i,v in enumerate(results):
            check_title = getTitle(v)
            check_title_2 = check_title.replace('-', ' ')
            scrubbed_check = ''.join(ch for ch in check_title if ch not in ch_exclude)

            check_word_list = filter(lambda x: x.lower() not in common_words \
                                        and len(x) > 2, scrubbed_check.split() )

            # Generate rank based on how many substring matches occurred.
            game_rank = 0

            # - Give perfect (100) rank to titles that match exactly
            if title.lower() == check_title.lower() \
                    or title.lower() == check_title.replace('-', '').lower() \
                    or title.lower() == check_title_2.lower():
                game_rank = 100
            # - Give high (99) rank to title if same words appear in result
            #   (e.g.  "The Legend of Zelda" --> "Legend of Zelda, The"
            elif sorted(word_list) == sorted(check_word_list):
                game_rank = 99
            # - Give high (95) rank to titles that appear entirely in results
            elif title.lower() in check_title.lower() \
                    or title.lower() in check_title.replace('-', '').lower() \
                    or title.lower() in check_title_2.lower():
                game_rank = 95
            # - Otherwise, rank title by number of occurrences of words
            else:
                game_rank = len( re.findall("(%s)" % '|'.join(word_list), check_title) )
            if game_rank:
                options.append((game_rank, getTitle(v), getGamePlatform(v), getId(v)))
        return options

    # Search for matching title options
    if len(results) > 1:
        options = sorted(getTitleOptions(title, results),
                         key=lambda x: (-x[0], x[1]))

    result = None
    while not result:
        # * I'm feeling lucky - select first result
        if args.l:
            if not options:     # If no options available, return None
                return None
            result = options[0]
            continue

        try:
            choice = chooseResult(options)
            if choice is None:
                print "Skipping game..."
                return None
            result = options[choice]
        except KeyboardInterrupt:
            raise KeyboardInterrupt
        except ManualTitleInterrupt:
            # Allow user to re-enter name of game title (manual search)
            readline.set_startup_hook(lambda: readline.insert_text(title))
            try:
                new_title = raw_input("Enter new title: ")
            finally:
                readline.set_startup_hook()
            print " ~ Searching for '%s' [%s]..." % (new_title, os.path.basename(file))
            options = sorted(getTitleOptions(new_title, results),
                             key=lambda x: (-x[0], x[1]))
        except Exception as e:
            print "Invalid selection (%s) " % e

    # Retrieve full game data using ID
    platform = getPlatformName(platformID)
    try:
        gamereq = urllib2.Request(GAMEINFO_URL, urllib.urlencode({'id': result[3], 'platform' : platform}),
                                  headers={'User-Agent' : "RetroPie Scraper Browser"})
        remotedata = urllib2.urlopen( gamereq )
        data = ET.parse(remotedata).getroot()
    except ET.ParseError:
        print "Malformed XML found, skipping game.. (source: {%s})" % URL
        return None
    return data.find("Game")

def getText(node):
    return normalize(node.text) if node is not None else None

def getId(nodes):
    return getText(nodes.find("id"))

def getTitle(nodes):
    if args.crc:
        return getText(nodes.find("title"))
    else:
        return getText(nodes.find("GameTitle"))

def getAlternateTitles(nodes):
    titles = []
    altNode = nodes.find("AlternateTitles")
    if altNode is not None:
        titles = [getText(t) for t in altNode.findall("title")]
    return titles

def getGamePlatform(nodes):
    if args.crc:
        return getText(nodes.find("system_title"))
    else:
        return getText(nodes.find("Platform"))

def getScummvmTitle(title):
    print "Fetching real title for %s from scummvm.org" % title
    URL  = "http://scummvm.org/compatibility/DEV/%s" % title.split("-")[0]
    data = "".join(urllib2.urlopen(URL).readlines())
    m    = re.search('<td>(.*)</td>', data)
    if m:
       print "Found real title %s for %s on scummvm.org" % (m.group(1), title)
       return m.groups()[0]
    else:
       print "No title found for %s on scummvm.org" % title
       return title

def getRealArcadeTitle(title):
    print "Fetching real title for %s from mamedb.com" % title
    URL  = "http://www.mamedb.com/game/%s" % title
    data = "".join(urllib2.urlopen(URL).readlines())
    m    = re.search('<b>Name:.*</b>(.+) .*<br/><b>Year', data)
    if m:
       print "Found real title %s for %s on mamedb.com" % (m.group(1), title)
       return m.group(1)
    else:
       print "No title found for %s on mamedb.com" % title
       return title

def getDescription(nodes):
    if args.crc:
        return getText(nodes.find("description"))
    else:
        return getText(nodes.find("Overview"))

def getImage(nodes):
    if args.crc:
        return getText(nodes.find("box_front"))
    else:
        return getText(nodes.find("Images/boxart[@side='front']"))

def getTGDBImgBase(nodes):
    return nodes.find("baseImgUrl").text

def getRelDate(nodes):
    if args.crc:
        return None
    else:
        return getText(nodes.find("ReleaseDate"))

def getPublisher(nodes):
    if args.crc:
        return None
    else:
        return getText(nodes.find("Publisher"))

def getDeveloper(nodes):
    if args.crc:
        return getText(nodes.find("developer"))
    else:
        return getText(nodes.find("Developer"))

def getRating(nodes):
    if args.crc:
        return None
    else:
        return getText(nodes.find("Rating"))

def getGenres(nodes):
    genres = []
    if args.crc and nodes.find("genre") is not None:
        for item in getText(nodes.find("genre")).split('>'):
            genres.append(item)
    elif nodes.find("Genres") is not None:
        for item in nodes.find("Genres").iter("genre"):
            genres.append(item.text)

    return genres if len(genres)>0 else None

def resizeImage(img, output):
    maxWidth = args.w
    maxHeight = args.t
    if img.size[0] > maxWidth or img.size[1] > maxHeight:
        if img.size[0] > maxWidth:
            print "Boxart over %spx (width). Resizing boxart.." % maxWidth
        elif img.size[1] > maxHeight:
            print "Boxart over %spx (height). Resizing boxart.." % maxHeight
        img.thumbnail((maxWidth, maxHeight), Image.ANTIALIAS)
        img.save(output)

def downloadBoxart(path, output):
    if args.crc:
        os.system("wget -q %s --output-document=\"%s\"" % (path,output))
    else:
        os.system("wget -q http://thegamesdb.net/banners/%s --output-document=\"%s\"" % (path,output))

def skipGame(list, filepath):
    for game in list.iter("game"):
        if game.findtext("path") == filepath:
            if args.v:
                print "Game \"%s\" already in gamelist. Skipping.." % os.path.basename(filepath)
            return True

def chooseResult(options):
    if len(options) > 0:
        count = 0
        for i, v in enumerate(options):
            rank  = v[0]
            title = v[1]
            try:
                print " [%s] %s  (+%s)" % (i, title, rank)
            except Exception as e:
                print "Exception! %s %s" % (e, title)
            count += 1
            if count >= 40:
                print "    ... Limiting to top 40 results (of %s) ..." % len(options)
                break
        print " [r] -> Enter new title to search"
        choice = raw_input("Select a result (or press Enter to skip): ")
        if choice in ['r', 'R']:
            raise ManualTitleInterrupt
        if not choice and choice != "0":
            return None
        return int(choice)
    else:
        print "* No options found. "
        choice = raw_input("Enter 'r' to search alternate title, or press Enter to skip): ")
        if choice in ['r', 'R']:
            raise ManualTitleInterrupt
        if not choice and choice != "0":
            return None
        raise ValueError


def autoChooseBestResult(nodes,t):
    results = nodes.findall('Game')
    t = t.split('(', 1)[0]
    if len(results) > 1:

        sep = ' |' # remove platform name
        lista = []
        listb = []
        listc = []
        for i,v in enumerate(results): # Do it backwards to eliminate false positives
            a = (str(getTitle(v).split(sep, 1)[0]).split('(', 1)[0])
            lista.append(a)
            listb.append(i)
        listc = list(lista)
        listc.sort(key=len)
        x = 0
        for n in reversed(listc):
            s = difflib.SequenceMatcher(None, t, lista[lista.index(n)]).ratio()
            if s > x:
                x = s
                xx = lista.index(n)
        ss = int(x * 100)
        print "Game Title Found  " + str(ss) + "% Chance : " + lista[xx]
        return xx
    else:
        return 0

def scanFiles(SystemInfo):
    name = SystemInfo[0]
    if name == "scummvm":
        global SCUMMVM
        SCUMMVM = True
    folderRoms = SystemInfo[1]
    extension = SystemInfo[2]
    platformID = SystemInfo[3]

    global gamelistExists
    global existinglist
    gamelistExists = False

    gamelist = Element('gameList')
    folderRoms = os.path.expanduser(folderRoms)

    if args.newpath is False:
        destinationFolder = folderRoms;
    else:
        destinationFolder = os.environ['HOME']+"/.emulationstation/%s/" % name
    try:
        os.chdir(destinationFolder)
    except OSError as e:
        print "%s : %s" % (destinationFolder, e.strerror)
        return

    platform_gamelist = getPlatformGameList(platformID)

    print "Scanning folder..(%s)" % folderRoms

    if os.path.exists("gamelist.xml"):
        try:
            existinglist = ET.parse("gamelist.xml")
            gamelistExists=True
            if args.v:
                print "Gamelist already exists: %s" % os.path.abspath("gamelist.xml")
        except:
            gamelistExists = False
            print "There was an error parsing the list or file is empty"

    for root, dirs, allfiles in os.walk(folderRoms, followlinks=True):
        allfiles.sort()
        for files in allfiles:
            if files.endswith(tuple(extension.split(' '))):
                try:
                    filepath = os.path.abspath(os.path.join(root, files))
                    filename = os.path.splitext(files)[0]

                    if gamelistExists and not args.f:
                        if skipGame(existinglist,filepath):
                            continue

                    print "\nTrying to identify %s.." % files

                    data = getGameInfo(filepath, platformID, platform_gamelist)

                    if data is None:
                        continue
                    else:
                        result = data

                    str_id = getId(result)
                    str_title = getTitle(result)
                    str_des = getDescription(result)
                    str_img = getImage(result)
                    str_rd = getRelDate(result)
                    str_pub = getPublisher(result)
                    str_dev = getDeveloper(result)
                    str_rating = getRating(result)
                    lst_genres = getGenres(result)

                    if str_title is not None:
                        game = SubElement(gamelist, 'game')
                        id = SubElement(game, 'id')
                        path = SubElement(game, 'path')
                        name = SubElement(game, 'name')
                        desc = SubElement(game, 'desc')
                        image = SubElement(game, 'image')
                        releasedate = SubElement(game, 'releasedate')
                        publisher = SubElement(game, 'publisher')
                        developer = SubElement(game, 'developer')
                        rating = SubElement(game, 'rating')
                        genres = SubElement(game, 'genres')

                        id.text = str_id
                        path.text = filepath
                        name.text = str_title
                        print "Game Found: %s" % str_title

                    if str_des is not None:
                        desc.text = str_des

                    if str_img is not None and args.noimg is False:
                        # Store boxart in a boxart/ folder (create if needed)
                        boxart_folder = os.path.abspath(os.path.join(root, 'boxart'))
                        if args.newpath is True:
                            boxart_folder = './boxart'

                        if not os.path.exists(boxart_folder):
                            os.mkdir(boxart_folder)

                        imgpath = os.path.join(boxart_folder, filename+os.path.splitext(str_img)[1])

                        print "Downloading boxart.."

                        downloadBoxart(str_img,imgpath)
                        imgpath = fixExtension(imgpath)
                        image.text = imgpath

                        if args.w or args.t:
                            try:
                                resizeImage(Image.open(imgpath), imgpath)
                            except Exception as e:
                                print "Image resize error"
                                print str(e)

                    if str_rd is not None:
                        releasedate.text = str_rd

                    if str_pub is not None:
                        publisher.text = str_pub

                    if str_dev is not None:
                        developer.text = str_dev

                    if str_rating is not None:
                        flt_rating = float(str_rating)
                        rating.text = "%.6f" % flt_rating
                    else:
                        rating.text = "0.000000"

                    if lst_genres is not None:
                        for genre in lst_genres:
                            newgenre = SubElement(genres, 'genre')
                            newgenre.text = genre.strip()
                except KeyboardInterrupt:
                    print "Ctrl+C detected. Closing work now..."
                    break
                except Exception as e:
                    print "Exception caught! %s" % e

    if gamelist.find("game") is None:
        print "No new games added."
    else:
        print "{} games added.".format(len(gamelist))
        exportList(gamelist)

try:
    if os.getuid() == 0:
        os.environ['HOME']="/home/"+os.getenv("SUDO_USER")
    config=open(os.environ['HOME']+"/.emulationstation/es_systems.cfg")
except IOError as e:
    sys.exit("Error when reading config file: %s \nExiting.." % e.strerror)

ES_systems = readConfig(config)
print parser.description

if args.pisize:
    print "Using Raspberry Pi boxart size: (%spx x %spx)" % (DEFAULT_WIDTH, DEFAULT_HEIGHT)
    args.w = DEFAULT_WIDTH
    args.t = DEFAULT_HEIGHT
else:
    if args.w:
        print "Max width set: %spx." % str(args.w)
        args.t = args.t if args.t else 999999
    if args.t:
        print "Max height set: %spx." % str(args.t)
        args.w = args.w if args.w else 999999
if args.noimg:
    print "Boxart downloading disabled."
if args.f:
    print "Re-scraping all games.."
if args.v:
    print "Verbose mode enabled."
if args.crc:
    print "CRC scraping enabled."
if args.p:
    print "Partial scraping enabled. Systems found:"
    for i,v in enumerate(ES_systems):
        print "[%s] %s" % (i,v[0])
    try:
        var = int(raw_input("System ID: "))
        scanFiles(ES_systems[var])
    except:
        sys.exit()
else:
    for i,v in enumerate(ES_systems):
        scanFiles(ES_systems[i])

print "All done!"
