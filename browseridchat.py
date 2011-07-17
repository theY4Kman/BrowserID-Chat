# BrowserID Chat
# A BrowserID-based secure chat site. Uses the Flask microframework and gevent
#     for network handling.
#
# Copyright (c) 2011 Zach "theY4Kman" Kanzler <they4kman@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import json
import redis
from gevent.wsgi import WSGIServer
from urllib2 import urlopen
from urllib import quote_plus
from xml.etree import ElementTree
from flask import Flask, render_template, request, redirect, url_for, session

app = Flask('browseridchat')
db = redis.Redis('localhost')

# Generate the secret key if it hasn't been already
if db.get('secretkey') is None:
  import os
  db.set('secretkey', os.urandom(36))
app.secret_key = db.get('secretkey')

@app.route('/')
def index():
  return render_template('index.htm')

@app.route('/logout/')
def logout():
  session.pop('email', None)
  return redirect(url_for('index'))

@app.route('/login/', methods=['POST', 'GET'])
def login():
  if request.method == 'POST':
    assertion = request.form['assertion']
    
    print request.environ
    url = 'https://browserid.org/verify?assertion=%s&audience=%s' % (
      quote_plus(assertion), request.environ.get('HTTP_HOST', 'localhost:5000'))
    http_resp = urlopen(url)
    resp = json.loads(http_resp.read())
    
    if resp['status'] == 'okay':
      email = resp['email']
      pubkey = None
      
      # Register them if they're not a returning user
      if db.sadd('users', email):
        # Grab their public key from browserid
        http_resp = urlopen('https://browserid.org/users/%s.xml' % email)
        xml = ElementTree.fromstring(http_resp.read())
        
        for elem in xml:
          if elem.tag.endswith('Link') and elem.attrib['rel'] == 'public-key':
            db.sadd('user:%s:pubkeys' % email, elem.attrib['value'])
        
        db.set('user:%s:messages' % email, 0)
      
      session['email'] = email
      return redirect(url_for('index'))
    else:
      return 'Error authenticating.<br />URL: %s<br /><br />Response: %s' % (url, resp)
  else:
    return render_template('login.htm')

def add_message(recipient, sender, message):
  """Add the message from sender to recipient's message list"""
  msg_id = db.incr('user:%s:messages' % recipient)
  db.sadd('user:%s:unread' % recipient, msg_id)
  db.set('user:%s:msg%d:content' % (recipient, msg_id), message)
  db.set('user:%s:msg%d:sender' % (recipient, msg_id), sender)

@app.route('/send/', methods=['POST'])
def send():
  if 'email' not in session:
    return 'notloggedin'
  
  recipient = request.form['recipient']
  message = request.form['message']
  
  if len(db.smembers('user:%s:pubkeys' % recipient)) == 0:
    return 'norecipientpubkeys'
  
  add_message(recipient, session['email'], message)
  return 'success'

@app.route('/get/')
def getmessages():
  response = {}
  
  if 'email' not in session:
    response['status'] = 'failure'
    response['reason'] = 'notloggedin'
    return json.dumps(response)
  
  email = session['email']
  messages = []
  for msg_id in db.smembers('user:%s:unread' % email):
    content = db.get('user:%s:msg%s:content' % (email, msg_id))
    sender = db.get('user:%s:msg%s:sender' % (email, msg_id))
    messages.append((sender, content))
  
  response['status'] = 'success'
  response['messages'] = messages
  return json.dumps(response)

app.debug = True
http_server = WSGIServer(('localhost', 5000), app)
http_server.serve_forever()