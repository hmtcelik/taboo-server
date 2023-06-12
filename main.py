import os
import json
import pandas as pd
from typing import Dict, List, Optional
from pydantic import BaseModel
from fastapi import FastAPI, Response, WebSocket, WebSocketDisconnect, status
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI()

origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

NO_TEAM = 0
RED_TEAM = 1
BLUE_TEAM = 2

init_data = {
    'clients': [],
    "is_started": False,
    "is_ended": False,
    "admin_id": "",
    "word": {"id":1, "word":"", "taboos":[]},
    "playing_info": {},
    "red_team": [],
    "blue_team": [],
    "timer": 0,
    "last_red_idx": -1,
    "last_blue_idx": -1,
    "last_team": 1,
}


data_path = os.getcwd() + '/data.json'

DF_WORDS = pd.read_json(data_path)

class ConnectionManager:
    def __init__(self):
        self.active_rooms: dict = {}

    async def connect(self, websocket: WebSocket, room_id:str):
        await websocket.accept()
        if room_id in self.active_rooms.keys():
            room_ = self.active_rooms[room_id]
            room_['connections'].append(websocket)
        else:
            self.active_rooms[room_id] = { 'id': room_id, 'last_word_idx': 0, 'connections':[websocket], 'data': init_data }

    async def disconnect(self, websocket: WebSocket, room_id:str, client_id:str):
        self.active_rooms[room_id]['connections'].remove(websocket)

        active_data = self.active_rooms[room_id]['data']

        new_clients = []
        for c in active_data['clients']:
            if c['id'] != client_id:
                new_clients.append(c)
        self.active_rooms[room_id]['data']['clients'] = new_clients

        res_data = self.active_rooms[room_id]['data']

        if self.active_rooms[room_id]['connections'] == []:
            self.active_rooms.pop(room_id)
            res_data = init_data

        await self.broadcast(res_data, room_id)

    async def broadcast(self, data, room_id):
        if room_id in self.active_rooms.keys():
            room_connections = self.active_rooms[room_id]['connections']

            for connection in room_connections:
                await connection.send_json(data)

manager = ConnectionManager()

@app.websocket("/ws/{room_id}/{client_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    client_id: str,
    room_id: str,
):
    '''
    connect server and communicate with websocket
    '''
    try:
        df_word = DF_WORDS.sample(frac=1).reset_index(drop=True).copy()
        await manager.connect(websocket, room_id)
        while True:
            res_data = {}
            data = await websocket.receive_json()

            if data['action'] == 'get_data':
                res_data = manager.active_rooms[room_id]['data']

            elif data['action'] == 'timer':
                if data['client_id'] == manager.active_rooms[room_id]['data']['admin_id']:
                    if manager.active_rooms[room_id]['data']['timer'] > 0:
                        manager.active_rooms[room_id]['data']['timer'] -= 1
                res_data = manager.active_rooms[room_id]['data']

            elif data['action'] == 'connect':
                active_data = manager.active_rooms[room_id]['data']
                room_data = {
                    'clients': active_data['clients'].copy(),
                    'is_started': active_data['is_started'],
                    'is_ended': active_data['is_ended'],
                    'admin_id': active_data['admin_id'],
                    'word': {"id":1, "word":"", "taboos":[]},
                    "playing_info": {},
                    "red_team": [],
                    "blue_team": [],
                    "last_team": 1,
                    "timer": 0
                }
                if active_data['is_started'] == True:
                    await manager.disconnect(websocket, room_id, client_id)

                is_admin = False
                client_ids_in_room = [i['id'] for i in room_data['clients']]
                if not data['client_id'] in client_ids_in_room:
                    if len(client_ids_in_room) <= 0:
                        is_admin = True
                    if is_admin:
                        room_data['admin_id'] = client_id
                    room_data['clients'].append({'id': data['client_id'], 'username': data['username'], 'team': NO_TEAM, 'score': 0, 'is_admin':is_admin})

                manager.active_rooms[room_id]['data'] = room_data
                res_data = manager.active_rooms[room_id]['data']

            elif data['action'] == 'set_team':
                res_data = manager.active_rooms[room_id]['data']
                
                for c in res_data['clients']:
                    if c['id'] == data['client_id']:
                        c['team'] = BLUE_TEAM if data['team'] == BLUE_TEAM else (RED_TEAM if data['team'] == RED_TEAM else NO_TEAM)

                manager.active_rooms[room_id]['data'] = res_data

            elif data['action'] == 'start_game':
                random_word = df_word.head(1)
                active_data = manager.active_rooms[room_id]['data']

                active_clients = active_data['clients'].copy()
                red_team = []
                blue_team = []
                for c in active_clients:
                    if c['team'] == 1:
                        red_team.append(c)
                    elif c['team'] == 2:
                        blue_team.append(c)

                room_data = {
                    'clients': active_clients,
                    'is_started': True,
                    'is_ended': False,
                    'admin_id': active_data['admin_id'],
                    'word': random_word.to_dict('records')[0],
                    "playing_info": red_team[0],
                    "last_red_idx": 0,
                    "last_blue_idx": -1,
                    "last_team": 1,
                    "red_team": red_team,
                    "blue_team": blue_team,
                    "timer": 60
                }
                manager.active_rooms[room_id]['data'] = room_data 
                manager.active_rooms[room_id]['last_word_idx'] = 0
                res_data = manager.active_rooms[room_id]['data']

            elif data['action'] == 'end_game':
                res_data = manager.active_rooms[room_id]['data']
                res_data['is_started'] = False
                res_data['is_ended'] = True

                manager.active_rooms[room_id]['data'] = res_data

            elif data['action'] == 'score':
                last_idx = manager.active_rooms[room_id]['last_word_idx']
                if last_idx+1 >= df_word.__len__():
                    last_idx = 0
                random_word = df_word[last_idx+1:last_idx+2]
                manager.active_rooms[room_id]['last_word_idx'] = last_idx+1

                active_data = manager.active_rooms[room_id]['data']
                room_data = {
                    'clients': active_data['clients'].copy(),
                    'is_started': active_data['is_started'],
                    'is_ended': active_data['is_ended'],
                    'admin_id': active_data['admin_id'],
                    'word': random_word.to_dict('records')[0],
                    "playing_info": active_data['playing_info'],
                    "red_team": active_data['red_team'],
                    "blue_team": active_data['blue_team'],
                    "timer": active_data['timer'],
                    "last_red_idx": active_data['last_red_idx'],
                    "last_blue_idx": active_data['last_blue_idx'],
                    "last_team": active_data['last_team']
                }
                new_clients = []
                for c in room_data['clients']:
                    if c['id'] == data['client_id']:
                        c['score'] +=  data['score']
                    new_clients.append(c)

                room_data['clients'] = new_clients
                manager.active_rooms[room_id]['data'] = room_data
                res_data = manager.active_rooms[room_id]['data']

            elif data['action'] == 'next_turn':
                last_idx = manager.active_rooms[room_id]['last_word_idx']
                if last_idx+1 >= df_word.__len__():
                    last_idx = 0
                random_word = df_word[last_idx+1:last_idx+2]
                manager.active_rooms[room_id]['last_word_idx'] = last_idx+1

                active_data = manager.active_rooms[room_id]['data']
                room_data = {
                    'clients': active_data['clients'].copy(),
                    'is_started': active_data['is_started'],
                    'is_ended': active_data['is_ended'],
                    'admin_id': active_data['admin_id'],
                    'word': random_word.to_dict('records')[0],
                    "playing_info": active_data['playing_info'],
                    "red_team": active_data['red_team'],
                    "blue_team": active_data['blue_team'],
                    "timer": 60,
                    "last_red_idx": active_data['last_red_idx'],
                    "last_blue_idx": active_data['last_blue_idx'],
                    "last_team": active_data['last_team']
                }

                if room_data['last_team'] == 1:
                    room_data['last_team'] = 2
                    if room_data['last_blue_idx'] +1 >= len(room_data['blue_team']):
                        room_data['last_blue_idx'] = -1
                    room_data['playing_info'] = room_data['blue_team'][room_data['last_blue_idx'] +1]
                    room_data['last_blue_idx'] += 1
                elif room_data['last_team'] == 2:
                    room_data['last_team'] = 1
                    if room_data['last_red_idx'] +1 >= len(room_data['red_team']):
                        room_data['last_red_idx'] = -1
                    room_data['playing_info'] = room_data['red_team'][room_data['last_red_idx'] +1]
                    room_data['last_red_idx'] += 1
                manager.active_rooms[room_id]['data'] = room_data
                res_data = manager.active_rooms[room_id]['data']

            await manager.broadcast(res_data, room_id)
    except WebSocketDisconnect:
        await manager.disconnect(websocket, room_id, client_id)


class Item(BaseModel):
    id: Optional[int] = 0
    word: str
    taboos: List[str]

@app.post("/_/word/")
async def create_item(response:Response,item: Item):
    '''
    Add new word to our dataset
    '''
    try:
        with open(data_path, 'r+') as f:
            data = json.load(f)
            df_words = pd.DataFrame(data)
            if item.word in df_words['word'].tolist():
                response.status_code = status.HTTP_400_BAD_REQUEST
                return {"success":False, "message": "this word is already exist", 'data':{}}
            new_id = df_words['id'].max() + 1
            item.id = int(new_id) if pd.notnull(new_id) else 1
            data.append(jsonable_encoder(item))
            f.seek(0)
            json.dump(data, f, indent=4)
            f.truncate()
        response.status_code = status.HTTP_200_OK
        return {"success":True, "message": "ok", 'data':{}}
    except Exception as e:
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return {"success":False, "message": str(e), 'data':{}}


@app.get("/_/word/")
async def get_items(response:Response):
    '''
    Add new word to our dataset
    '''
    try:
        with open(data_path, 'r+') as f:
            data = json.load(f)
        df_words = pd.DataFrame(data)
        response.status_code = status.HTTP_200_OK
        return {"success":True, "message": "ok", 'data':df_words.to_dict(orient='records')}
    except Exception as e:
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return {"success":False, "message": str(e), 'data':{}}


@app.delete("/_/word/{word_id}/")
async def delete_item(response:Response, word_id:int):
    '''
    Add new word to our dataset
    '''
    try:
        with open(data_path, 'r+') as f:
            data = json.load(f)
            df_words = pd.DataFrame(data)
            if not word_id in df_words['id'].tolist():
                response.status_code = status.HTTP_400_BAD_REQUEST
                return {"success":False, "message": "this word is not exist", 'data':{}}
            df_words = df_words[df_words['id']!=word_id]
            data = df_words.to_dict('records')
            f.seek(0)
            json.dump(data, f, indent=4)
            f.truncate()
        response.status_code = status.HTTP_200_OK
        return {"success":True, "message": "ok", 'data':{}}
    except Exception as e:
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return {"success":False, "message": str(e), 'data':{}}


if __name__ == "__main__":
  uvicorn.run("main:app", host="0.0.0.0", port=8765, reload=True)
