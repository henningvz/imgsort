import tkinter as tk
import glob
import os
import piexif
import re
import sys, getopt
import geopy
import pathlib
import shutil
import certifi
import ssl
from tqdm import tqdm

from datetime import datetime
import filecmp

from PIL import Image
from PIL.ExifTags import TAGS

from tkinter import filedialog
from os import listdir
from os import walk

from PIL.ExifTags import TAGS
from PIL.ExifTags import GPSTAGS
import geopy.geocoders
from geopy.geocoders import Nominatim
from dataclasses import dataclass


g_whatsapp_regex= re.compile(r"(IMG|VID)-(\d{8})-WA(\d{4})\.\w*$")
ctx = ssl.create_default_context(cafile=certifi.where())
geopy.geocoders.options.default_ssl_context = ctx
g_geolocator = Nominatim(user_agent="imgsort",scheme="http")
g_exif_DateTimeOriginal_idx = 36867
g_exif_DateTimeOriginal_format = "%Y:%m:%d %H:%M:%S"
g_whatsapp_date_format ="%Y%m%d"


def get_exif_from_file(filename):
    image = Image.open(filename)
    image.verify()
    return image.getexif()

def get_labeled_exif(exif):
    if not exif:
        raise ValueError("No EXIF metadata found")
    labeled = {}
    for (key, val) in exif.items():
        labeled[TAGS.get(key)] = val
    return labeled

def get_geotagging(exif):
    if not exif:
        raise ValueError("No EXIF metadata found")
    geotag = {}
    for (idx, tag) in TAGS.items():
        if tag == 'GPSInfo' and idx in exif:
            gps_info = exif.get_ifd(idx)
            for (key, val) in GPSTAGS.items():
                if key in gps_info:
                    geotag[val] = gps_info[key]
    return geotag

def get_decimal_from_dms(dms, ref):
    degrees = float(dms[0])
    minutes = float(dms[1]) / 60.0
    seconds = float(dms[2]) / 3600.0
    #flip sign
    if ref in ['S', 'W']:
        degrees = -degrees
        minutes = -minutes
        seconds = -seconds
    return round(degrees + minutes + seconds, 5)

def get_coordinates(geotags):
    if 'GPSLatitude' in geotags and 'GPSLongitude' in geotags:
        lat = get_decimal_from_dms(geotags['GPSLatitude'], geotags['GPSLatitudeRef'])
        lon = get_decimal_from_dms(geotags['GPSLongitude'], geotags['GPSLongitudeRef'])
        return (lat,lon)
    else:
        return ()
    
def get_date_taken(exif):
    if not exif:
        raise ValueError("No EXIF metadata found")
    result = ""
    if g_exif_DateTimeOriginal_idx in exif:
        result = exif[g_exif_DateTimeOriginal_idx]
    return result

def get_date_taken_fallback(filename):
    #try whatsapp
    base = os.path.basename(filename)
    wa_match = g_whatsapp_regex.match(base)
    result = ""
    if wa_match:
        date_str = wa_match.group(2)
        result = datetime.strptime(date_str, g_whatsapp_date_format).strftime(g_exif_DateTimeOriginal_format)
    else:
        #use creation date
        fname = pathlib.Path(filename)
        mtime = datetime.fromtimestamp(fname.stat().st_mtime)
        result = mtime.strftime(g_exif_DateTimeOriginal_format)
    return result

def is_whatsapp_image(filename):
    base = os.path.basename(filename)
    return g_whatsapp_regex.match(base)

def get_raw_location(coordinates):
    location = g_geolocator.reverse(coordinates, language="de")
    return location.raw

def get_year_str(date):
    return str(datetime.strptime(date, g_exif_DateTimeOriginal_format).year)

def get_month_str(date):
    return str(datetime.strptime(date, g_exif_DateTimeOriginal_format).month).zfill(2)

def compile_address_string_from_raw_location(location):
    elements = []
    dict = location['address']

    #first level
    if 'county' in dict:
        elements.append(dict['county'])
    elif 'state' in dict:
        elements.append(dict['state'])
    elif 'country' in dict:
        elements.append(dict['country'])

    #second level
    if 'village' in dict:
        elements.append(dict['village'])
    elif 'town' in dict:
        elements.append(dict['town'])
    elif 'city' in dict:
        elements.append(dict['city'])
    
    #join and compress
    result = '_'.join(elements)

    result = re.sub("[/\\ ]","-",result)
    result = re.sub("-+","-",result)
    result = re.sub("_+","_",result)
    result = re.sub(r"\(.*?\)","",result)
    
    return result
    
def move_ex(source, dest, shallow = False):
    if not os.path.exists(source):
        raise FileNotFoundError(source)

    if os.path.exists(dest):
        #destination already exists
        if os.path.samefile(source,dest):
            #nothing to do, same file
            return dest

        if filecmp.cmp(source,dest, shallow = shallow):
            #file content is identical, just remove source
            os.remove(source)
            return dest

        #files are different: try 1000 times to find another name
        (root,ext) = os.path.splitext(dest)
        
        for idx in range (0,1000):
            dest_try = root + "-" + str(idx).zfill(3) + ext
            if os.path.exists(dest_try):
                if filecmp.cmp(source, dest_try, shallow = shallow):
                    #file content is identical, just remove source
                    os.remove(source)
                    return dest_try
            else:
                #success, we found a new name
                return shutil.move(source, dest_try)
        
        # give up and raise exception
        raise FileExistsError(dest_try)
    else:
        #ready to move
        return shutil.move(source,dest)

def copy_ex(source, dest, shallow = False):
    if not os.path.exists(source):
        raise FileNotFoundError(source)

    if os.path.exists(dest):
        #destination already exists
        if os.path.samefile(source,dest):
            #nothing to do, same file
            return dest

        if filecmp.cmp(source,dest, shallow = shallow):
            #file content is identical, just remove source
            return dest

        #files are different: try 1000 times to find another name
        (root,ext) = os.path.splitext(dest)
        
        for idx in range (0,1000):
            dest_try = root + "-" + str(idx).zfill(3) + ext
            if os.path.exists(dest_try):
                if filecmp.cmp(source, dest_try, shallow = shallow):
                    #file content is identical, just remove source
                    return dest_try
            else:
                #success, we found a new name
                return shutil.copy2(source, dest_try)
        
        # give up and raise exception
        raise FileExistsError(dest_try)
    else:
        #ready to move
        return shutil.copy2(source,dest)

def glob_images(src_dir):
    # glob all jpegs
    extensions = ['*.jpg','*.jpeg']
    jpeg_files = []

    if os.path.exists(src_dir):
        for ext in extensions:
            jpeg_files.extend( glob.glob(src_dir+"/**/"+ext, recursive=True))

    return jpeg_files

def main(argv):
    root= tk.Tk()
    root.withdraw()

    teststring = " Alcante /Alicante"
    newstring = teststring.split("/",1)[0]
    
    src_root_dir = filedialog.askdirectory()
    dest_root_dir = filedialog.askdirectory()

    src_files = glob_images(src_root_dir)

    print("pyimagesort: Found " + str(len(src_files)) + " image(s) in src dir.")

    for file in tqdm(src_files, desc="Processing Images", ncols=40):
        exif = get_exif_from_file(file)
        time_str = ""
        address_str = ""
        if exif:
            time_str = get_date_taken(exif)
            geotags = get_geotagging(exif)
            if geotags:
                latlon = get_coordinates(geotags)
                if latlon:
                    loc = get_raw_location(latlon)
                    address_str = compile_address_string_from_raw_location(loc)
        
        if not time_str:
            #no timestr, try fallbacks
            time_str = get_date_taken_fallback(file)
        
        dest_path_str = ""
        dest_dir = dest_root_dir

        if time_str:
            dest_dir = os.path.join(dest_dir, get_year_str(time_str))
            dest_path_str = get_year_str(time_str) + "-" + get_month_str(time_str)
        else:
            dest_dir = os.path.join(dest_dir, "0000")
            dest_path_str = "0000-00"
                        
        if address_str:
            dest_path_str += "_" + address_str
        else:
            dest_path_str += "_Misc"

        dest_dir = os.path.join(dest_dir, dest_path_str)

        if not os.path.exists(dest_dir):
            os.makedirs(dest_dir)
        
        dest_file_path = os.path.join(dest_dir, os.path.basename(file))
        move_ex(file, dest_file_path)

        src_dir = os.path.dirname(file)

        if len(os.listdir(src_dir)) == 0: # Check is empty..
            os.rmdir(src_dir) # Delete..



if __name__ == "__main__":
    main(sys.argv[1:])




    









