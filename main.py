import json
import pandas as pd
from typing import Dict, List, Optional
from pydantic import BaseModel
from fastapi import FastAPI, Response, WebSocket, WebSocketDisconnect, status
from fastapi.encoders import jsonable_encoder

app = FastAPI()

NO_TEAM = 0
RED_TEAM = 1
BLUE_TEAM = 2

init_data = {
    'clients': [],
    "is_started": False,
    "is_ended": False
}

class ConnectionManager:
    def __init__(self):
        self.active_rooms: dict = {}

    async def connect(self, websocket: WebSocket, room_id:str):
        await websocket.accept()
        if room_id in self.active_rooms.keys():
            room_ = self.active_rooms[room_id]
            room_['connections'].append(websocket)
        else:
            self.active_rooms[room_id] = { 'id': room_id, 'connections':[websocket], 'data': init_data }

    def disconnect(self, websocket: WebSocket, room_id:str):
        self.active_rooms[room_id]['connections'].remove(websocket)
        if self.active_rooms[room_id]['connections'] == []:
            self.active_rooms.pop(room_id)

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
        await manager.connect(websocket, room_id)
        while True:
            res_data = {}
            data = await websocket.receive_json()

            if data['action'] == 'get_data':
                res_data = manager.active_rooms[room_id]['data']

            elif data['action'] == 'connect':
                res_data = manager.active_rooms[room_id]['data']

                if res_data['is_started'] == True:
                    manager.disconnect(websocket, room_id)

                client_ids_in_room = [i['id'] for i in res_data['clients']]
                if not data['client_id'] in client_ids_in_room:
                    res_data['clients'].append({'id':data['client_id'], 'username': data['username'], 'team': NO_TEAM, 'score':0})

                manager.active_rooms[room_id]['data'] = res_data

            elif data['action'] == 'set_team':
                res_data = manager.active_rooms[room_id]['data']
                
                for c in res_data['clients']:
                    if c['id'] == data['client_id']:
                        c['team'] = BLUE_TEAM if data['team'] == BLUE_TEAM else (RED_TEAM if data['team'] == RED_TEAM else NO_TEAM)

                manager.active_rooms[room_id]['data'] = res_data

            elif data['action'] == 'start_game':
                res_data = manager.active_rooms[room_id]['data']
                res_data['is_ended'] = False
                res_data['is_started'] = True

                manager.active_rooms[room_id]['data'] = res_data

            elif data['action'] == 'end_game':
                res_data = manager.active_rooms[room_id]['data']
                res_data['is_started'] = False
                res_data['is_ended'] = True

                manager.active_rooms[room_id]['data'] = res_data

            elif data['action'] == 'score':
                res_data = manager.active_rooms[room_id]['data']
                for c in res_data['clients']:
                    if c['id'] == data['client_id']:
                        c['score'] +=  data['score']

                manager.active_rooms[room_id]['data'] = res_data

            await manager.broadcast(res_data, room_id)
    except WebSocketDisconnect:
        manager.disconnect(websocket, room_id)


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
        with open('data.json', 'r+') as f:
            data = json.load(f)
            df_words = pd.DataFrame(data)
            if item.word in df_words['word'].tolist():
                response.status_code = status.HTTP_400_BAD_REQUEST
                return {"success":False, "message": "this word is already exist", 'data':{}}
            item.id = df_words['id'].max() + 1
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
        with open('data.json', 'r+') as f:
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
        with open('data.json', 'r+') as f:
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
