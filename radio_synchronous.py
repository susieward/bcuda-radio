import paho.mqtt.client as mqtt
import serial
import alsaaudio
import time
import atexit

#setup audio mixer for volume
mixer = alsaaudio.Mixer()
#setup arduino serial
#arduino = serial.Serial(port='/dev/ttyACM0', baudrate=11520,timeout=.03)
#arduino.flush()

mqtt.Client.connect_flag = False
client = mqtt.Client("python1")

class MessageService:
    def __init__(self):
        self.current_artist = ''
        self.current_title = ''
        self.current_track_length = 0
        self.current_progress = "0/0/0"

        self.artist_stale = True
        self.title_stale = True
        self.progress_stale = True

        self.last_sent_frame_duration = 0
        self.last_sent_artist = ""
        self.last_sent_title = ""

    def on_message(self, client, userdata, message):
        message_string = message.payload.decode("utf-8")
        topic = message.topic
        print('got message', message)
        print("topic:", topic)
        if topic == "bcuda/artist":
            self.process_artist(message_string)
        elif topic == "bcuda/title":
            self.process_title(message_string)
        elif topic == "bcuda/ssnc/prgr":
            self.process_progress(message_string)
        elif topic == "bcuda/play_end":
            print("pause trigger")
        elif topic == "bcuda/play_start":
            print("play trigger")
        else:
            print("topic:",message.topic)

    def process_artist(self, message):
        message = message.upper()
        message = message.replace("|"," ")
        self.current_artist = message
        self.artist_stale = False
       # print(current_artist)
        self.send_data_if_ready()

    def process_title(self, message):
        message = message.upper()
        message = message.replace("|"," ")
        self.current_title = message
        self.title_stale = False
        #print(current_title)
        self.send_data_if_ready()

    def process_progress(self, message):
        self.current_progress = message
        self.progress_stale = False
        #print(current_progress)
        self.send_data_if_ready()

    def send_data_if_ready(self):
        if not self.artist_stale and not self.title_stale and not self.progress_stale:
            #break the prgr into something comprehensible
            timestamps = self.current_progress.split("/")
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
            message_string = self.current_title + "|" + self.current_artist + "|" + str(track_current_time) + "|" + str(track_duration) + "\n"
            current_frame_duration = rtp_end - rtp_begin
            #check if this is the old timestamp on the new data (which happens 90% of song changes
            if self.song_and_duration_match(current_frame_duration):
                self.last_sent_frame_duration = current_frame_duration
                self.last_sent_artist = self.current_artist
                self.last_sent_title = self.current_title
                #set all data to stale
                self.artist_stale = True
                self.title_stale = True
                self.progress_stale = True
                #send it to the arduino
                print(message_string)
                #arduino.write(message_string.encode('utf-8'))
    #a hack to handle when a song is skipped and the prgr is sent for the previous song,
    #resulting in the new song being sent with the old song's duration and progress
    def song_and_duration_match(self, current_frame_duration):
        if current_frame_duration == self.last_sent_frame_duration:
            if not self.last_sent_artist == self.current_artist and not self.last_sent_title == self.current_title:
                return False
        return True


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
    pass
    #commands = arduino.readline().decode('ascii').rstrip()
    #parse_commands(commands)

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

def on_connect(client, userdata, flags, rc):
    if rc==0:
        client.connect_flag=True
        print("connected")
        topics = (
            'bcuda/title',
            'bcuda/artist',
            'bcuda/ssnc/prgr',
            'bcuda/play_start',
            'bcuda/play_end'
        )
        for topic in topics:
            client.subscribe(topic)
    else:
        print("connection failed",rc)

def mqtt_disconnect():
    print("exiting")
    client.loop_stop
    client.disconnect()

def main():
    service = MessageService()

    client.on_connect = on_connect
    client.on_message = service.on_message

    broker = "localhost"
    client.connect(broker)
    client.loop_start()

    time.sleep(4)

    #main area
    #topics = ['title', 'artist', 'ssnc/prgr', 'play_start', 'play_end']

    #for topic in topics:
        #client.subscribe(f'bcuda/{topic}')

    while True:
        receive_commands()
    atexit.register(mqtt_disconnect)

main()
