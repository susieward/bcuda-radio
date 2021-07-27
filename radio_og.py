import paho.mqtt.client as mqtt
import serial
import alsaaudio
import time
import atexit

current_artist = ""
current_title = ""
current_track_length = 0
current_progress = "0/0/0"

artist_stale = True
title_stale = True
progress_stale = True

last_sent_frame_duration = 0

def on_connect(client, userdata, flags, rc):
    if rc==0:
        client.connect_flag=True
        print("connected")
    else:
            print("connection failed",rc)

def on_message(client, userdata, message):
    message_string = str(message.payload.decode("utf-8"))
    #print("topic:",message.topic)
    if message.topic == "bcuda/artist":
        process_artist(message_string)
    if message.topic == "bcuda/title":
        process_title(message_string)
    if message.topic == "bcuda/ssnc/prgr":
        process_progress(message_string)
    if message.topic == "bcuda/play_end":
        print("pause trigger")
    if message.topic == "bcuda/play_start":
        print("play trigger")
    

def send_data_if_ready():
    global artist_stale, title_stale, progress_stale, current_artist, current_title, current_progress, last_sent_frame_duration, last_sent_artist, last_sent_title 
    if not artist_stale and not title_stale and not progress_stale:
        #break the prgr into something comprehensible
        timestamps = current_progress.split("/")
        rtp_begin = int(timestamps[0])
        rtp_current = int(timestamps[1])
        rtp_end = int(timestamps[2])
        
        #44,100hz is airplay frequency, so we divide by that to get the seconds
        track_current_time = int((rtp_current - rtp_begin) / 44100)
        track_duration = int((rtp_end - rtp_begin) / 44100)
        #I've seen a weird bug where the first song played after connecting computes
        #a current time way longer than the song's duration.
        if track_current_time > track_duration:
            track_current_time = 0
        message_string = current_title + "|" + current_artist + "|" + str(track_current_time) + "|" + str(track_duration) + "\n"
        current_frame_duration = rtp_end - rtp_begin
        #check if this is the old timestamp on the new data (which happens 90% of song changes      
        if song_and_duration_match(current_frame_duration):
            last_sent_frame_duration = current_frame_duration
            last_sent_artist = current_artist
            last_sent_title = current_title
            #set all data to stale
            artist_stale = True
            title_stale = True
            progress_stale = True
            #send it to the arduino
            print(message_string)
            arduino.write(message_string.encode('utf-8'))
#a hack to handle when a song is skipped and the prgr is sent for the previous song,
#resulting in the new song being sent with the old song's duration and progress
def song_and_duration_match(current_frame_duration):
    global last_sent_frame_duration, current_artist, current_title, last_sent_artist, last_sent_title
    if current_frame_duration == last_sent_frame_duration:
        if not last_sent_artist == current_artist and not last_sent_title == current_title:
            return False
    return True
    
def process_artist(message):
    global current_artist, artist_stale
    message = message.upper()
    message = message.replace("|"," ")
    current_artist = message
    artist_stale = False
   # print(current_artist)
    send_data_if_ready()
def process_title(message):
    global current_title, title_stale
    message = message.upper()
    message = message.replace("|"," ")
    current_title = message
    title_stale = False
    #print(current_title)
    send_data_if_ready()
def process_progress(message):
    global current_progress, progress_stale
    current_progress = message
    progress_stale = False
    #print(current_progress)
    send_data_if_ready()
    
def play_pause():
    client.publish("bcuda/remote", "playpause")
    #print("play/pause")
def next_track():
    client.publish("bcuda/remote", "nextitem")
def prev_track():
    client.publish("bcuda/remote", "previtem")
#set volume to value between 0 and 100%
def set_volume(volume_level):
    global mixer
    if volume_level > 100:
        volume_level = 100
    if volume_level < 0:
        volume_level = 0
    mixer.setvolume(int(volume_level))
    print(int(volume_level))
    
def receive_commands():
    commands = arduino.readline().decode('ascii').rstrip()
    parse_commands(commands)
    
def parse_commands(commands):
    if "buttons" in commands:
        button_code = commands.split(":")
        execute_buttons(int(button_code[1]))
    if "volume" in commands:
        volume_level = commands.split(":")
        set_volume(int(volume_level[1]))

def execute_buttons(button_code):
    if button_code == 4:
        play_pause()
    if button_code == 2:
       next_track()
    if button_code == 8:
        prev_track()
def mqtt_disconnect():
    print("exiting")
    client.loop_stop
    client.disconnect()
#setup audio mixer for volume
mixer = alsaaudio.Mixer()
#setup arduino serial
arduino = serial.Serial(port='/dev/ttyACM0', baudrate=11520,timeout=.03)
arduino.flush()

mqtt.Client.connect_flag=False
broker="localhost"
client=mqtt.Client("python1")
client.on_connect=on_connect
client.on_message = on_message
client.connect(broker)
client.loop_start()

time.sleep(4)
   
#main area
client.subscribe("bcuda/title")
client.subscribe("bcuda/artist")
client.subscribe("bcuda/ssnc/prgr")
client.subscribe("bcuda/play_start")
client.subscribe("bcuda/play_end")
while True:
    receive_commands()
atexit.register(mqtt_disconnect)

