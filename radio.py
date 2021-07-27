import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
from asyncio_mqtt import Client, MqttError
import serial
import alsaaudio

#setup audio mixer for volume
mixer = alsaaudio.Mixer()
#setup arduino serial
#arduino = serial.Serial(port='/dev/ttyACM0', baudrate=11520,timeout=.03)
#arduino.flush()
#mqtt.Client.connect_flag = False
#client = mqtt.Client("python1")

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

    def on_message(self, message):
        message_string = message.payload.decode("utf-8")
        topic = message.topic
        if topic == "bcuda/artist":
            self.process_message(message_string, 'artist')
        elif topic == "bcuda/title":
            self.process_message(message_string, 'title')
        elif topic == "bcuda/ssnc/prgr":
            self.process_message(message_string, 'progress')
        elif topic == "bcuda/play_end":
            print("pause trigger")
        elif topic == "bcuda/play_start":
            print("play trigger")
        elif topic == "bcuda/ssnc/mdst":
            print('metadata start')
        elif topic == "bcuda/ssnc/mden":
            print('metadata end')

    def process_message(self, message, msg_type):
        if msg_type == 'artist' or msg_type == 'title':
            message = message.upper().replace("|"," ")
        setattr(self, f'current_{msg_type}', message)
        setattr(self, f'{msg_type}_stale', False)
        if not self.artist_stale and not self.title_stale and not self.progress_stale:
            self.send_data_if_ready()

    def format_message(self, track_current_time, track_duration):
        return self.current_title + "|" + self.current_artist + "|" + str(track_current_time) + "|" + str(track_duration) + "\n"

    def send_data_if_ready(self):
        (track_current_time, track_duration, current_frame_duration) = self.process_timestamps()
        message_string = self.format_message(track_current_time, track_duration)

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

    def process_timestamps(self):
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
        current_frame_duration = rtp_end - rtp_begin
        return (track_current_time, track_duration, current_frame_duration)

    #a hack to handle when a song is skipped and the prgr is sent for the previous song,
    #resulting in the new song being sent with the old song's duration and progress
    def song_and_duration_match(self, current_frame_duration):
        if current_frame_duration == self.last_sent_frame_duration:
            if not self.last_sent_artist == self.current_artist and not self.last_sent_title == self.current_title:
                return False
        return True


class RadioRemote:
    def __init__(self, client):
        self.client = client
        self.mixer = mixer

    def receive_commands(self):
        pass
        #with serial.Serial(port='/dev/ttyACM0', baudrate=11520,timeout=.03) as arduino:
            #commands = arduino.readline().decode('ascii').rstrip()
            #self.parse_commands(commands)

    def parse_commands(self, commands):
        if "buttons" in commands:
            button_code = commands.split(":")
            self.execute_buttons(int(button_code[1]))
        if "volume" in commands:
            volume_level = commands.split(":")
            self.set_volume(int(volume_level[1]))

    def execute_buttons(self, button_code):
        if button_code == 4:
            self.play_pause()
        elif button_code == 2:
            self.next_track()
        elif button_code == 8:
            self.prev_track()

    def play_pause(self):
        self.client.publish("bcuda/remote", "playpause")
        #print("play/pause")

    def next_track(self):
        self.client.publish("bcuda/remote", "nextitem")

    def prev_track(self):
        self.client.publish("bcuda/remote", "previtem")

    #set volume to value between 0 and 100%
    def set_volume(self, volume_level):
        if volume_level > 100:
            volume_level = 100
        if volume_level < 0:
            volume_level = 0
        self.mixer.setvolume(int(volume_level))
        print(int(volume_level))


async def start():
    async with AsyncExitStack() as stack:
        # Keep track of the asyncio tasks we create so we can cancel them on exit
        tasks = set()
        stack.push_async_callback(cancel_tasks, tasks)

        service = MessageService()
        # Connect to the MQTT broker
        broker = "localhost"
        client = Client(broker)
        await stack.enter_async_context(client)

        topics = (
            'bcuda/title',
            'bcuda/artist',
            'bcuda/ssnc/prgr',
            'bcuda/play_start',
            'bcuda/play_end',
            'bcuda/ssnc/mdst',
            'bcuda/ssnc/mden'
        )
        for topic in topics:
            manager = client.filtered_messages(topic)
            messages = await stack.enter_async_context(manager)
            task = asyncio.create_task(handle_messages(messages, service, topic))
            tasks.add(task)

        # Subscribe to topics
        await client.subscribe("bcuda/#")

        remote = RadioRemote(client)
        remote.receive_commands()

        # Wait for everything to complete (or fail)
        await asyncio.gather(*tasks)


async def handle_messages(messages, service, topic):
    async for message in messages:
        msg = f"{message.topic}: {message.payload.decode('utf-8')}"
        print(msg)
        service.on_message(message)
        #print(message.payload.decode('utf-8'))

async def cancel_tasks(tasks):
    for task in tasks:
        if task.done():
            continue
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

async def main():
    reconnect_interval = 3
    while True:
        try:
            await start()
        except MqttError as error:
            print(f'Error "{error}". Reconnecting in {reconnect_interval} seconds.')
        finally:
            await asyncio.sleep(reconnect_interval)


asyncio.run(main())
