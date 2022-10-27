import json
import random
import socket
import sys
import math
import time
import uuid
from copy import copy, deepcopy
import threading

import pygame
from pygame import mixer
from pygame import Rect
from pygame.math import Vector2

import headered_socket

def find_childless(entity):

    if entity.child is None:
        return entity

    # if this one doesnt have a child, then we look at its child's child property
    childless = find_childless(entity) # this function will return an entity with no child

    return childless

def round_down(n):
    return int(math.floor(n / 20.0)) * 20

def create_update(update_type, entity_type=None, entity_id=None, data=None, json_bytes=False):
    # conditions that must be true if we are making a create update

    match update_type:
        case "create":
            if entity_type is None or data is None:
                raise Exception("Must supply entity_type and data arguments when making CREATE update")

        case "update":
            if entity_id is None or data is None:
                raise Exception("Must supply entity_id and data arguments when making UPDATE update")

        case "delete":
            if entity_id is None:
                raise Exception("Must supply entity_id argument when making DELETE update")

        case "sound":
            if data is None:
                raise Exception("Must supply data argument when making SOUND update")

    update = {
        "update_type": update_type,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "data": data
    }

    if json_bytes:
        return bytes(json.dumps(update), "utf-8")

    return update

class State:
    def __init__(self, entities={}, updates=[], sounds=[]):
        self.entities = entities
        self.updates = updates
        self.sounds = sounds

        # the vector we use to offset all entities and make a camera effect
        self.camera_offset = Vector2()

        self.mouse_pos = pygame.mouse.get_pos()

        # amount of time since last frame
        self.dt = 0

class Entity:
    def __init__(self, rect, sprite_path, owner=None, visible=True, entity_id=None, velocity=Vector2(0, 0),
                 scale_res=None):

        # the one that updates this every frame
        self.owner = owner

        self.rect = rect

        self.velocity = velocity

        self.sprite_path = sprite_path

        self.sprite = pygame.image.load(sprite_path)

        #print(type(self.sprite))

        self.visible = visible

        # this indicates to the game that we want to delete the object from the state
        self.delete = False

        self.entity_id = entity_id

        # we use the object id to identify objects. that way we can update existing objects
        if entity_id == None:  # if no object id is supplied we make one
            self.entity_id = str(uuid.uuid4())

        # all the functions that will be executed every frame
        self.update_funcs = [
            self.move
        ]

        self.scale_res = scale_res

        self.entity_type = "entity"

        # scale the sprite if a scale res is specified
        if scale_res and sprite_path:
            self.sprite = pygame.transform.scale(self.sprite, scale_res)

    @staticmethod
    def create_from_dict(entity_dict):

        rect = Rect(entity_dict["rect"])
        sprite_path = entity_dict["sprite_path"]
        owner = entity_dict["owner"]
        visible = entity_dict["visible"]
        entity_id = entity_dict["entity_id"]
        velocity = Vector2(entity_dict["velocity"])
        scale_res = entity_dict["scale_res"]

        new_object = Entity(rect=rect, sprite_path=sprite_path, owner=owner, visible=visible, entity_id=entity_id,
                            velocity=velocity, scale_res=scale_res)

        return new_object

    def load_update(self, update_data):

        for key in update_data.keys():

            match key:
                case "rect":
                    self.rect.x, self.rect.y, self.rect.width, self.rect.height = update_data["rect"]
                case "sprite_path":
                    self.sprite_path = update_data["sprite_path"]
                case "owner":
                    self.owner = update_data["owner"]
                case "visible":
                    self.visible = update_data["visible"]
                case "entity_id":
                    self.entity_id = update_data["entity_id"]
                case "velocity":
                    self.velocity.x, self.velocity.y = update_data["velocity"]
                case "scale_res":
                    self.scale_res = update_data["scale_res"]

    def dump_to_dict(self):

        data_dict = {}

        data_dict["rect"] = [self.rect.x, self.rect.y, self.rect.width, self.rect.height]
        data_dict["sprite_path"] = self.sprite_path
        data_dict["owner"] = self.owner
        data_dict["visible"] = self.visible
        data_dict["entity_id"] = self.entity_id
        data_dict["velocity"] = [self.velocity.x, self.velocity.y]
        data_dict["scale_res"] = self.scale_res

        return data_dict

    def detect_collisions(self, entities):

        # list of entities that collide with this object
        collisions = []

        for entity in entities.values():
            # tests if this entities rect overlaps with
            if self.rect.colliderect(entity.rect):
                collisions.append(entity)

        return collisions

    def move(self, state):

        # VELOCITY IS THE AMOUNT THE OBJECT WILL MOVE IN ONE FRAME

        # move the entities rect

        #print(self.velocity)

        # we dont need to move the entity if they have no velocity
        if self.velocity == Vector2(0,0):
            return

        self.rect.move_ip(
            self.velocity
        )

        update_data = {
            "rect": [self.rect.x, self.rect.y, self.rect.width, self.rect.height]
        }

        # add the update to the queue
        state.updates.append(
            create_update(update_type="update", entity_id=self.entity_id, data=update_data)
        )

        #print(self.velocity)

class SnakeHead(Entity):
    def __init__(self, rect, sprite_path="assets/square.png", owner=None, visible=True, entity_id=None, velocity=Vector2(0, 0),
                 scale_res=(20,20)):

        super().__init__(rect, sprite_path, owner, visible, entity_id, velocity,
                 scale_res)

        # we only move once every 1/3 second, so we need to keep track of this
        self.last_moved = 0

        # we have the actual velocity, which is the amount we move in a given frame
        # but we also have a different velocity which is saved between changes to the actual one
        self.bts_velocity = Vector2(0,0) # I do not have a better name for this at the moment

        # the snake body entity that follows the head
        self.child = None

        self.update_funcs.extend(
            (self.accelerate,)
        )

    def consume(self, state):
        # check to see if we are colliding with any food, and make snake bigger if we do
        collisions = self.detect_collisions(state.entities)

        for entity in collisions:
            if type(entity) is not Food:
                continue

            if self.rect.colliderect(entity.rect) is False:
                continue

            # look down the chain of snake body entites until we find one without a child
            childless = find_childless(self)

            # when creating snake babies they start out really far away, because theres really no way of knowing
            # where they are supposed to be
            # they only appear behind the snake once it has moved once
            childless.child = SnakeBody(rect=Rect(50000, 0, 20, 20))

    def accelerate(self, state):

        # only allow movement if we havent moved in the past 1/3 second
        #print(time.time() - self.last_moved)

        keys = pygame.key.get_pressed()

        if keys[pygame.K_w]:
            print("up")
            self.bts_velocity.y = -20

            # we cancel all horizontal movement if we move up
            self.bts_velocity.x = 0

        elif keys[pygame.K_s]:
            self.bts_velocity.y = 20

            self.bts_velocity.x = 0

        elif keys[pygame.K_a]:
            self.bts_velocity.y = 0

            self.bts_velocity.x = -20

        elif keys[pygame.K_d]:
            self.bts_velocity.y = 0

            self.bts_velocity.x = 20

        # only set the real velocity to bts velocity very third of a second
        if time.time() - self.last_moved < 0.1:
            self.velocity = Vector2(0, 0)

            return

        # set the actual frame velocity to the requested velocity by the user
        self.velocity = self.bts_velocity

        self.last_moved = time.time()


        # SOMETHING WITH THE LAST RECT OR SOMETHING I NEED TO SLEEP

class Food(Entity):
    def __init__(self, rect, sprite_path="assets/square.png", owner=None, visible=True, entity_id=None, velocity=Vector2(0, 0),
                 scale_res=(20,20)):

        super().__init__(rect, sprite_path, owner, visible, entity_id, velocity,
                 scale_res)

class SnakeBody(Entity):
    def __init__(self, rect, sprite_path="assets/square.png", owner=None, visible=True, entity_id=None,
                 velocity=Vector2(0, 0),
                 scale_res=(20, 20)):
        super().__init__(rect, sprite_path, owner, visible, entity_id, velocity,
                         scale_res)

class Game:
    def __init__(self, is_server=True):

        pygame.init()
        mixer.init()

        self.is_server = is_server

        if is_server:
            self.client_accepter = headered_socket.HeaderedSocket(socket.AF_INET)
            self.client_accepter.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.client_accepter.bind((socket.gethostname(), 5570))
            self.client_accepter.listen(5)
            self.client_accepter.setblocking(False)

        self.server = headered_socket.HeaderedSocket(socket.AF_INET)

        # our client ID
        self.uuid = str(uuid.uuid4())

        self.state = State()

        # our screen surface
        self.screen = pygame.display.set_mode([1920, 1080])

        self.clock = pygame.time.Clock()

        # we use this map to translate network update types to actual entity types
        self.entity_map = {
            "snake_head": SnakeHead
        }

        # is our client connected to a server
        self.connected = False

        # the mouse position we recorded on the previous frame
        self.last_mouse_pos = pygame.mouse.get_pos()

    def accept_clients(self):

        clients = []

        while True:

            try:
                # try to accept the client socket
                client, address = self.client_accepter.accept()

                # send the new client a bunch of create updates with all the current entities we have
                initial_create_updates = []

                for entity_id, entity in self.state.entities.items():
                    # make a create update for each entity
                    update = create_update("create", entity_type=entity.entity_type, data=entity.dump_to_dict())

                    initial_create_updates.append(update)

                # convert the updates to json
                initial_create_updates_json = json.dumps(initial_create_updates)

                # only send the initial create updates if there are existing entities
                if initial_create_updates != []:
                    # send the updates to the client
                    client.send_headered(
                        bytes(initial_create_updates_json, "utf-8")
                    )

                    print(f"Sent initial update containing {len(initial_create_updates)} entities")

                # add the client to our list of client sockets
                clients.append(client)

            except BlockingIOError:
                pass
                # if there are no connections to accept then we just skip it

            for updating_client in clients:

                try:
                    # see if we have an update from the client
                    updates = updating_client.recv_headered()

                    #print(updates.decode("utf-8"))

                except BlockingIOError:
                    continue  # continue to the next client if we didnt receive an update

                # forward the updates to all the clients
                for client in clients:

                    # dont send the update to the client that sent it
                    if client is updating_client:
                        continue

                    client.send_headered(updates)

    def send_update(self, update):

        if update != []: # if they did not provide a list of updates, we put it in a list for them
            update = [update]

        update_json = json.dumps(update)

        update_bytes = bytes(update_json, "utf-8")

        self.server.send_headered(update_bytes)

    def dump_state(self):

        state_dict = {}

        for entity_id, entity in self.state.entities.items():
            state_dict[entity_id] = entity.dump_to_dict()

        return state_dict

    def connect(self, ip):

        # connect the server socket
        self.server.connect((ip, 5570))

        self.server.setblocking(False)  # only disable blocking when we are fully connected

        self.connected = True

    def receive_network_updates(self):

        # if we arent connected then we dont receive updates
        if not self.connected:
            return

        # get updates from the server
        try:
            server_updates_json = self.server.recv_headered().decode("utf-8")
        except BlockingIOError:
            return  # if there is no updates to read, then we skip

        server_updates = json.loads(server_updates_json)

        #print(server_updates)

        for update in server_updates:

            match update["update_type"]:

                case "create":

                    #print("Create!")

                    # get entity that is to be created
                    entity_class = self.entity_map[
                        update["entity_type"]
                    ]

                    new_entity = entity_class.create_from_dict(
                        update["data"]
                    )

                    #print(type(new_entity))

                    #print(update["data"])
                    # add the new entity to the state
                    self.state.entities[new_entity.entity_id] = new_entity

                case "update":

                    #print("Update!")

                    # find the entity in the state and update it with the provided data
                    self.state.entities[update["entity_id"]].load_update(update["data"])

                case "delete":

                    #print("Delete!")

                    del self.state.entities[update["entity_id"]]

                case "sound":

                    print("new sounds")

                    self.state.sounds.append(
                        update["data"]["path"]
                    )

    def start(self):
        # creates all the initial entities we need to play

        local_snake_head = SnakeHead(rect=Rect(300, 300, 20, 20), owner=self.uuid)

        self.state.entities[local_snake_head.entity_id] = local_snake_head

    def update(self):

        dt = self.clock.tick(60) / 1000

        fps = self.clock.get_fps()

        #print(int(fps))

        self.state.dt = dt

        self.screen.fill((100, 100, 100))

        # updates that will be sent this frame
        self.state.updates = []

        # sounds that will be played this frame
        self.state.sounds = []

        self.receive_network_updates()

        # we move the camera if the user is right clicking and dragging the mouse3
        if pygame.mouse.get_pressed()[2]:

            # the pixels that the mouse moved since the last frame
            mouse_delta = (
                pygame.mouse.get_pos()[0] - self.last_mouse_pos[0],
                pygame.mouse.get_pos()[1] - self.last_mouse_pos[1]
            )

            self.state.camera_offset.x += mouse_delta[0]
            self.state.camera_offset.y += mouse_delta[1]

        # calculates what the mouse pos should be after we add the camera offset
        mouse_pos = pygame.mouse.get_pos()

        self.state.mouse_pos = (
            mouse_pos[0] - self.state.camera_offset.x,
            mouse_pos[1] - self.state.camera_offset.y
        )

        #print(self.state.camera_offset)

        #print(self.state.mouse_pos)

        self.last_mouse_pos = pygame.mouse.get_pos()

        for entity_id, entity in copy(self.state.entities).items():

            if entity.delete:
                del self.state.entities[entity_id]

                continue

            if entity.owner == self.uuid:  # only update the entity if we own it
                for function in entity.update_funcs:
                    function(self.state)

            if entity.visible:

                # calculate rect AFTER camera offset is applied
                offset_rect = entity.rect.move(self.state.camera_offset)

                self.screen.blit(entity.sprite, offset_rect)

        for sound in self.state.sounds:
            sound_object = mixer.Sound(sound)

            sound_object.play()

            print("playing!")

        pygame.display.update()

        # if we have no updates then we dont send one
        if self.state.updates == []:
            return

        updates_json = json.dumps(self.state.updates)

        if self.connected:  # only send update if we are connected
            # send our update the server
            self.server.send_headered(
                bytes(updates_json, "utf-8")
            )

    def run(self):

        if self.is_server:
            new_client_thread = threading.Thread(target=self.accept_clients, daemon=True)
            new_client_thread.start()

        self.start()

        # self.connect(socket.gethostname())

        while True:

            events = pygame.event.get()

            for event in events:
                if event.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit()

            #before_dict = frozendict(self.local_state)
            self.update()
            #after_dict = self.local_state

            #updates = self.detect_changes(before_dict, after_dict)

            # print(updates)

response = input("Host game? (y/N): ")

match response.lower():
    case "y":
        is_server = True

        ip = socket.gethostname()
        print("Hosting server!")

    case _:
        is_server = False

        ip = input("Enter IP: ")

        if ip == "":
            ip = socket.gethostname()

        print("Connecting to remote server")


game = Game(is_server=is_server)

game.connect(ip)

game.run()
