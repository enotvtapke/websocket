import base64
import hashlib
import socket
import sys
import codecs
import json
import random
import time
import asyncio
import os

class Timer:
  def __init__(self, timeout, callback):
      self._timeout = timeout
      self._callback = callback
      self._task = asyncio.ensure_future(self._job())

  async def _job(self):
      await asyncio.sleep(self._timeout)
      await self._callback()

  def cancel(self):
    try:
      self._task.cancel()
    except asyncio.CancelledError:
      raise
    except Exception:
      pass

class Room:
  def __init__(self, env, host, words, mode = "normal", maxplayers = 8, maxround = 15, roundtime = 120, password = "", **kwargs):
    self.host = host
    self.users = [host]
    self.env = env

    self.score = {host: 0}
    self.mode = mode
    self.words = words
    self.round = 0
    self.maxround = int(maxround)
    self.roundtime = int(roundtime)
    self.maxplayers = int(maxplayers)
    self.choosedWords = []
    self.password = password

    self.keyword = None

    self.startTime = 0;
    self.timer = None

  async def add(self, user):
    print("Adding new user to room\n")
    try:
      self.users.index(user)
    except ValueError:
      self.users.append(user)

    if self.online() == 2 and self.round == 0:
      await self.startRound()

    await self.updateScore(user)

  async def kick(self, user):
    if self.online() <= 1: 
      return 2
    if user == self.host:
      self.changeHost()
      if self.score.get(user) != None:
        self.score.pop(user)
      self.users.remove(user)
      print("Kicked user " + user)
      print("Current online: " + str(self.online()))
      await self.sendall('{"type":"players", "players":' + json.dumps(self.score) + '}')
      
      await self.startRound()
    else:
      if self.score.get(user) != None:
        self.score.pop(user)
      self.users.remove(user)
      print("Kicked user " + user)
      await self.sendall('{"type":"players", "players":' + json.dumps(self.score) + '}')

  def changeHost(self):
    self.users.append(self.users.pop(0))
    self.host = self.users[0]

  async def send(self, user, msg):
    client = self.env.clients.get(user)
    if client == None:
      await self.kick(user)
    else:
      self.env.sendto(client, msg)

  async def sendall(self, msg):
    for user in self.users:
        await self.send(user, msg)

  async def updateScore(self, user, points = 0):
    self.score[user] = int(points)
    await self.sendall('{"type":"players", "players":' + json.dumps(self.score) + '}')

  def online(self):
    return len(self.users)

  async def startRound(self):
    print("startRound\n")
    if self.timer != None:
      self.timer.cancel()
    self.round = (self.round + 1) % (self.maxround + 1);
    await self.sendall('{"type":"roundstart", "round":"%s", "host":"%s"}' % (str(self.round), self.host))
    await self.sendWords()

  def chooseWords(self, count):
    choosen = []
    for i in range(count):
      word = self.words.pop(0)
      self.words.append(word)
      choosen.append(word)
    self.choosedWords = choosen
    return choosen

  async def sendWords(self):
    if self.online() < 1: return 2
    await self.send(self.host, '{"type":"words", "words":' + json.dumps(self.chooseWords(3)) + '}')
    self.timer = Timer(7, self.sendKeyword)

  async def sendKeyword(self):
    word = self.choosedWords[random.randint(0, 2)]
    await self.send(self.host, '{"type":"keyword", "keyword":' + json.dumps(word) + '}')
    self.onKeyword(word)

  def onKeyword(self, keyword):
    self.keyword = keyword
    self.startTime = time.monotonic()
    self.timer.cancel()
    self.timer = Timer(self.roundtime, self.endRound)

  async def win(self, winner):
    print("win\n")
    self.timer.cancel()
    wintime = self.startTime - time.monotonic()
    self.score[winner] += 20
    self.score[self.host] += 20
    await self.endRound(winner)

  async def endRound(self, winner = ""):
    print("endRound\n")
    await self.sendall('{"type":"roundend", "score":' + json.dumps(self.score) + ', "winner":"' + winner + '", "painter":"' + self.host + '", "keyword":"' + self.keyword + '", "lastround":"' + json.dumps(self.round == self.maxround) + '"}')
    self.changeHost()
    self.timer = Timer(10, self.startRound)

class WebSocketServer: 
  def __init__(self, host, port, limit, **kwargs): 
    """
    Initialize websocket server. 
    :param host: Host name as IP address or text definition. 
    :param port: Port number, which server will listen. 
    :param limit: Limit of connections in queue. 
    :param kwargs: A dict of key/value pairs. It MAY contains:<br> 
    <b>onconnect</b> - function, called after client connected. 
    <b>handshake</b> - string, containing the handshake pattern. 
    <b>magic</b> - string, containing "magic" key, required for "handshake". 
    :type host: str 
    :type port: int 
    :type limit: int 
    :type kwargs: dict 
    """
    self.host = host 
    self.port = port 
    self.limit = limit 
    self.running = False 
    self.clients = {} 
    self.args = kwargs 

  async def start(self): 
    """ 
    Start websocket server. 
    """ 
    self.root = socket.socket(socket.AF_INET, socket.SOCK_STREAM) 
    self.root.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) 
    self.root.bind((self.host, self.port)) 
    self.root.listen(self.limit) 
    self.root.setblocking(False)
    self.running = True 

    while self.running:
      try:
        client, address = await a_loop.sock_accept(self.root)
        if not self.running: break 
        if (await self.handshake(client)):
          onconnect = self.args.get("onconnect") 
          if callable(onconnect): onconnect(self, client, address) 

          a_loop.create_task(self.loop(client, address))
      except KeyboardInterrupt:
        self.stop()

    self.root.close()



  def stop(self): 
    """ 
    Stop websocket server. 
    """ 
    self.running = False
    print("Server stopped")


  async def handshake(self, client):
    handshake = 'HTTP/1.1 101 Switching Protocols\r\nConnection: Upgrade\r\nUpgrade: websocket\r\nSec-WebSocket-Accept: %s\r\n\r\n' 
    handshake = self.args.get('handshake', handshake) 
    magic = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11" 
    magic = self.args.get('magic', magic) 
    header = str(await a_loop.sock_recv(client, 1000))
    try: 
      res = header.index("Sec-Websocket-Key")
    except ValueError:
      return False

    key = header[res + 19: res + 19 + 24] 
    key += magic
    key = hashlib.sha1(key.encode()) 
    key = base64.b64encode(key.digest()) 
    client.send(bytes((handshake % str(key,'utf-8')), 'utf-8'))
    return True 



  async def loop(self, client, address):
    print ("Loop started")
    is_alive = True
    clientName = None
    while is_alive:
      m = await a_loop.sock_recv(client, 65536)
      fin, text = await self.decodeFrame(m)
      
      if not fin: 
        onmessage = self.args.get('onmessage') 
        if callable(onmessage):
          clientName = await onmessage(self, client, text)
        else: 
          print("onmessage don`t callable")
      else:
        if self.clients.get(clientName) != None:
          del self.clients[clientName]
        ondisconnect = self.args.get('ondisconnect')
        if callable(ondisconnect): 
          await ondisconnect(self, clientName, address) 
        client.close()
        return False




  async def decodeFrame(self, data): 
    """
     0                   1                   2                   3
     0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
    +-+-+-+-+-------+-+-------------+-------------------------------+
    |F|R|R|R| опкод |М| Длина тела  |    Расширенная длина тела     |
    |I|S|S|S|(4бита)|А|   (7бит)    |            (1 байт)           |
    |N|V|V|V|       |С|             |(если длина тела==126 или 127) |
    | |1|2|3|       |К|             |                               |
    | | | | |       |А|             |                               |
    +-+-+-+-+-------+-+-------------+ - - - - - - - - - - - - - - - +
    """

    if (len(data) == 0) or (data is None): 
      return True, None 

    fin = (data[0] == 0x88)
    if fin: 
      return fin, None

    masked = data[1] >> 7 == 1

    plen = data[1] - (128 if masked else 0)
    mask_start = 2 
    if plen == 126: 
      mask_start = 4 
      plen = int(codecs.encode(data[2:4], 'hex'), 16)
    elif plen == 127: 
      mask_start = 10 
      plen = int(codecs.encode(data[2:10], 'hex'), 16)

    mask = data[mask_start:mask_start+4]
    data = data[mask_start+4:mask_start+4+plen]

    decoded = [] 
    i = 0 
    while i < len(data): 
      decoded.append(data[i]^mask[i%4]) 
      i+=1 

    text = str(bytearray(decoded), "utf-8") 
    return fin, text 



  def sendto(self, client, data, **kwargs):
    print ("Send:")
    """ 
    Send <b>data</b> to <b>client</b>. <b>data</b> can be of type <i>str</i>, <i>bytes</i>, <i>bytearray</i>, <i>int</i>. 
    :param client: Client socket for data exchange. 
    :param data: Data, which will be sent to the client via <i>socket</i>. 
    :type client: socket 
    :type data: str|bytes|bytearray|int|float 
    """ 
    if type(data) == bytes or type(data) == bytearray: 
      frame = data 
    elif type(data) == str: 
      frame = bytes(data, kwargs.get('encoding', 'utf-8')) 
    elif type(data) == int or type(data) == float: 
      frame = bytes(str(data), kwargs.get('encoding', 'utf-8')) 
    else: #10000001
      print(type(data))
      return None 

    framelen = len(frame) 
    head = bytes([0x81])

    if framelen < 126: 
      head += bytes(int.to_bytes(framelen, 1, 'big')) 
    elif 126 <= framelen < 0x10000: 
      head += bytes([126])
      head += bytes(int.to_bytes(framelen, 2, 'big'))
    else: 
      head += bytes(127) 
      head += bytes(int.to_bytes(framelen, 8, 'big'))
    print(head + frame)
    print("\n") 
    client.send(head + frame) 

rooms = {}
async def onmessage (self, client, text):
  print("Message received: \n" + text + "\n")

  jsontext = json.loads(text)
  mtype = jsontext["type"]
  if mtype == "ping":
    self.sendto(client, '{"type":"pong"}')
  elif mtype == "login":
    if self.clients.get(jsontext["client"]) == None:
      self.clients.update({jsontext["client"]: client})
      self.sendto(client, '{"type":"login", "success": "1"}')
    else:
      self.sendto(client, '{"type":"login", "success": "0"}')
      self.sendto(client, '{"type":"error", "error":"Client already log in"}')
      return None
  elif mtype == "room":
    if self.clients.get(jsontext["client"]) != None:
      room = rooms.get(jsontext["room"])
      if room != None:
        if room.password == "" or jsontext.get("password") == room.password:
          await room.add(jsontext["client"])
          self.sendto(client, '{"type":"room", "success":1, "clients":' + json.dumps(room.score) + '}')
        else:
          self.sendto(client, '{"type":"room", "success":0, "error":"Invalid password"}')
      else:
        self.sendto(client, '{"type":"room", "success":0}')
        self.sendto(client, '{"type":"error", "error":"Room \'' + jsontext["room"] + '\' does not exist"}')
        return None
    else:
      self.sendto(client, '{"type":"room", "success":0}')
      self.sendto(client, '{"type":"error", "error":"Unlogged client"}')
      return None
  elif mtype == "createroom":
    if self.clients.get(jsontext["client"]) != None:
      if rooms.get(jsontext["room"]) == None:
        room = Room(self, host = jsontext["client"], words = json.loads(jsontext["words"]), roundtime = jsontext["roundtime"], maxround = jsontext["maxround"], mode = jsontext["mode"], maxplayers = jsontext["maxplayers"], password = jsontext["password"])
        rooms.update({jsontext["room"]: room})
        self.sendto(client, '{"type":"createroom", "success":1}')
      else:
        self.sendto(client, '{"type":"createroom", "success":0, "error":"Name \'' + jsontext["room"] + '\' already used"}')
        self.sendto(client, '{"type":"error", "error":"Name \'' + jsontext["room"] + '\' already used"}')
        return None
    else:
      self.sendto(client, '{"type":"createroom", "success":0}')
      self.sendto(client, '{"type":"error", "error":"Unlogged client"}')
      return None
  elif mtype == "getrooms":
    if self.clients.get(jsontext["client"]) != None:
      self.sendto(client, '{"type":"getrooms", "rooms":' + roomstojson(rooms) + '}')
    else:
      self.sendto(client, '{"type":"getrooms", "success":0}')
      self.sendto(client, '{"type":"error", "error":"Unlogged client"}')
      return None
  elif mtype == "keyword":
    if self.clients.get(jsontext["client"]) != None:
      room = rooms.get(jsontext["room"])
      if room != None:
        room.onKeyword(jsontext["keyword"])
      else:
        self.sendto(client, '{"type":"keyword", "success":0}')
        self.sendto(client, '{"type":"error", "error":"Room \'' + jsontext["room"] + '\' does not exist"}')
        return None
    else:
      self.sendto(client, '{"type":"keyword", "success":0}')
      self.sendto(client, '{"type":"error", "error":"Unlogged client"}')
      return None
  elif mtype == "win":
    if self.clients.get(jsontext["client"]) != None:
      room = rooms.get(jsontext["room"])
      if room != None:
        await room.win(jsontext["winner"])
      else:
        self.sendto(client, '{"type":"win", "success":0}')
        self.sendto(client, '{"type":"error", "error":"Room \'' + jsontext["room"] + '\' does not exist"}')
        return None
    else:
      self.sendto(client, '{"type":"win", "success":0}')
      self.sendto(client, '{"type":"error", "error":"Unlogged client"}')
      return None
  elif mtype == "exit":
    room = rooms.get(jsontext["room"])
    if room != None:
      await room.kick(jsontext["client"])
  else:
    if self.clients.get(jsontext["client"]) != None:
      if self.clients.get(jsontext["receiver"]) != None:
        self.sendto(self.clients.get(jsontext["receiver"]), text)
      else:
        self.sendto(client, '{"type":"error", "error":"Invalid receiver"}')
        return None
    else:
        self.sendto(client, '{"type":"error", "error":"Unlogged client"}')
        return None

  return jsontext["client"]

def roomstojson(rooms):
  jrooms = {};
  for room, param in rooms.items():
    jrooms.update({room:{"players":param.online(), "maxplayers":param.maxplayers, "mode":param.mode, "round":param.round, "maxround":param.maxround, "roundtime":param.roundtime, "password": "" if param.password == "" else "1"}})

  return json.dumps(jrooms);

def onconnect (self, client, address):
  print("------- New connection -------\nAdress: " + address[0] + "\n")

async def ondisconnect(self, clientName, address):
  if clientName != None:
    for roomname, room in rooms.items():
      if clientName in room.users:
        code = await room.kick(clientName)
        if (code == 2):
          print("Delete room with name " + roomname)
          del rooms[roomname]
          break
  print("User with IP " + address[0] + " and name '" + str(clientName) + "' disconnected")
  print("\n")




sigServ = WebSocketServer("0.0.0.0", int(os.environ.get('PORT', 80)), 4, **{"onmessage": onmessage, "onconnect": onconnect, "ondisconnect": ondisconnect})

a_loop = asyncio.get_event_loop()
a_loop.run_until_complete(sigServ.start())