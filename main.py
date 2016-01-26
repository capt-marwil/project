from flask import Flask, render_template, request, redirect, jsonify, url_for, \
    flash, make_response
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, relationship
from flask_wtf import Form
from wtforms import StringField, SubmitField, TextField, FileField
from wtforms.validators import DataRequired
from setup_database import Base, expeditions_categories, Expedition, Item, Category, User
from flask import session as login_session
from oauth2client.client import flow_from_clientsecrets
from oauth2client.client import FlowExchangeError
import httplib2
import json
import requests
import random
import string


app = Flask(__name__)

CLIENT_ID = json.loads(
    open('client_secrets.json', 'r').read())['web']['client_id']
APPLICATION_NAME = "Expedition Packing list App"

""" Connect to Database and create a database session """
engine = create_engine('sqlite:///catalog.db')
Base.metadata.bind = engine

DBSession = sessionmaker(bind=engine)
session = DBSession()


""" Routes """

""" routes that don't require an login """


@app.route('/')
@app.route('/catalog')
def index():
    logged_in = True
    if 'username' not in login_session:
        logged_in = False
    expeditions = session.query(Expedition).order_by(Expedition.title)
    if expeditions is None:
        return render_template('index.html', logged_id=logged_in)
    for e in expeditions:
        print e.id
    return render_template('index.html', expeditions=expeditions,
                           logged_in=logged_in)


@app.route('/expedition/<int:expedition_id>/')
def expedition(expedition_id):
    expedition = session.query(Expedition).filter_by(id=expedition_id).one()
    #categories = None
    categories = session.query(Category).filter(Category.expedition.any(id=expedition_id))
    return render_template('expedition.html', expedition=expedition,
                           categories=categories)


@app.route('/expedition/<int:expedition_id>/category/<int:category_id>')
def category(expedition_id, category_id):
    expedition = session.query(Expedition).filter_by(id=expedition_id).one()
    category = session.query(Category).filter_by(id=category_id).one()
    items = session.query(Item).filter_by(category_id=category_id, expedition_id=expedition_id).all()
    return render_template('category.html', category=category, expedition=expedition, items=items)


@app.route('/expedition/<int:expedition_id>/category/<int:category_id>/'
           'item/<int:item_id>', methods=['GET', 'POST'])
def item(expedition_id, category_id, item_id):
    pass


""" routes to login and to logout """


# Create anti-forgery state token
@app.route('/login')
def showLogin():
    state = ''.join(random.choice(string.ascii_uppercase + string.digits)
                    for x in xrange(32))
    login_session['state'] = state
    # return "The current session state is %s" % login_session['state']
    return render_template('login.html', STATE=state)


@app.route('/gconnect', methods=['POST'])
def gconnect():
    # Validate state token
    if request.args.get('state') != login_session['state']:
        response = make_response(json.dumps('Invalid state parameter.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    # Obtain authorization code
    code = request.data

    try:
        # Upgrade the authorization code into a credentials object
        oauth_flow = flow_from_clientsecrets('client_secrets.json', scope='')
        oauth_flow.redirect_uri = 'postmessage'
        credentials = oauth_flow.step2_exchange(code)
    except FlowExchangeError:
        response = make_response(
            json.dumps('Failed to upgrade the authorization code.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Check that the access token is valid.
    access_token = credentials.access_token
    url = ('https://www.googleapis.com/oauth2/v1/tokeninfo?access_token=%s'
           % access_token)
    h = httplib2.Http()
    result = json.loads(h.request(url, 'GET')[1])
    # If there was an error in the access token info, abort.
    if result.get('error') is not None:
        response = make_response(json.dumps(result.get('error')), 500)
        response.headers['Content-Type'] = 'application/json'

    # Verify that the access token is used for the intended user.
    gplus_id = credentials.id_token['sub']
    if result['user_id'] != gplus_id:
        response = make_response(
            json.dumps("Token's user ID doesn't match given user ID."), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Verify that the access token is valid for this app.
    if result['issued_to'] != CLIENT_ID:
        response = make_response(
            json.dumps("Token's client ID does not match app's."), 401)
        print "Token's client ID does not match app's."
        response.headers['Content-Type'] = 'application/json'
        return response

    stored_access_token = login_session.get('access_token')
    stored_gplus_id = login_session.get('gplus_id')
    if stored_access_token is not None and gplus_id == stored_gplus_id:
        response = make_response(json.dumps('Current user is already connected.'),
                                 200)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Store the access token in the session for later use.
    login_session['access_token'] = credentials.access_token
    login_session['gplus_id'] = gplus_id

    # Get user info
    userinfo_url = "https://www.googleapis.com/oauth2/v1/userinfo"
    params = {'access_token': credentials.access_token, 'alt': 'json'}
    answer = requests.get(userinfo_url, params=params)

    data = answer.json()

    login_session['username'] = data['name']
    login_session['picture'] = data['picture']
    login_session['email'] = data['email']

    # check whether user exists in local database
    if getUserID(login_session['email']):
        getUserInfo(getUserID(login_session['email']))
    else:
        CreateUser(login_session)


    output = ''
    output += '<h1>Welcome, '
    output += login_session['username']
    output += '!</h1>'
    output += '<img src="'
    output += login_session['picture']
    output += ' " style = "width: 300px; height: 300px;border-radius: 150px;-webkit-border-radius: 150px;-moz-border-radius: 150px;"> '
    flash("you are now logged in as %s" % login_session['username'])
    print "done!"
    return output

    # DISCONNECT - Revoke a current user's token and reset their login_session


@app.route('/gdisconnect')
def gdisconnect():
    access_token = login_session['access_token']
    print 'In gdisconnect access token is %s', access_token
    print 'User name is: '
    print login_session['username']
    if access_token is None:
        print 'Access Token is None'
        response = make_response(json.dumps('Current user not connected.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    url = 'https://accounts.google.com/o/oauth2/revoke?token=%s' % login_session['access_token']
    h = httplib2.Http()
    result = h.request(url, 'GET')[0]
    print 'result is '
    print result
    if result['status'] == '200':
        del login_session['access_token']
        del login_session['gplus_id']
        del login_session['username']
        del login_session['email']
        del login_session['picture']
        response = make_response(json.dumps('Successfully disconnected.'), 200)
        response.headers['Content-Type'] = 'application/json'
        return response
    else:
        response = make_response(json.dumps('Failed to revoke token for given user.', 400))
        response.headers['Content-Type'] = 'application/json'
        return response


@app.route('/login')
def login():
    return render_template('login.html')

""" routes to add, edit and delete database entities require a valid login """

""" routes to manipulate Expdition entity """
@app.route('/expedition/new', methods=['GET', 'POST'])
def addExpedition():
    if 'username' not in login_session:
        return redirect('/login')
    if request.method == 'POST':
        newExpedition = Expedition(title=request.form['title'],
                                   description=request.form['description'],
                                   picture=request.form['picture'],
                                   user_id=user_id)
        session.add(Expedition)
        flash('New Expedition %s has been created' % newExpedition.title)
        session.commit()
        return redirect(url_for('index'))
    else:
        return render_template('addExpedition.html')


@app.route('/expedition/<int:expedition_id>/edit', methods=['GET', 'POST'])
def editExpedition(expedition_id):
    if 'username' not in login_session:
        return redirect('/login')


@app.route('/expedition/<int:expedition_id>/'
           'delete', methods=['GET', 'POST'])
def deleteRoute(expedition_id):
   if 'username' not in login_session:
        return redirect('/login')


""" routes to manipulate Category entity """


@app.route('/expedition/<int:expedition_id>/category/'
           'new/', methods=['GET', 'POST'])
def addCategory(expedition_id, category_id):
    if 'username' not in login_session:
        return redirect('/login')


@app.route('/expedition/<int:expedition_id>/category/<int:category_id>/'
           'edit', methods=['GET', 'POST'])
def editCategory(expedition_id, category_id):
    if 'username' not in login_session:
        return redirect('/login')


@app.route('/expedition/<int:expedition_id>/category/<int:category_id>/'
           'delete', methods=['GET', 'POST'])
def deleteCategory(expedition_id, category_id):
    if 'username' not in login_session:
        return redirect('/login')


""" routes to manipulate Item entity """


@app.route('/expedition/<int:expedition_id>/category/<int:category_id>/item/'
           'new/', methods=['GET', 'POST'])
def addItem(expedition_id, category_id, item_id):
    if 'username' not in login_session:
        return redirect('/login')


@app.route('/expedition/<int:expedition_id>/category/<int:category_id>/item/'
           '<int:item_id>/edit', methods=['GET', 'POST'])
def editItem(expedition_id, category_id, item_id):
    if 'username' not in login_session:
        return redirect('/login')


@app.route('/expedition/<int:expedition_id>/category/<int:category_id>/item/'
           '<int:item_id>/delete/', methods=['GET', 'POST'])
def deleteItem(expedition_id, category_id, item_id):
    if 'username' not in login_session:
        return redirect('/login')


""" Create and edit Users in the database """
def getUserID(email):
    try:
        user = session.query(User).filter_by(email=email).one()
        return user.id
    except:
        return None


def getUserInfo(user_id):
    user = session.query(User).filter_by(id=user_id).one()
    return user


def CreateUser(login_session):
    NewUser = User(name=login_session['username'],
                   email=login_session['email'],
                   picture=login_session['picture'])
    session.add(NewUser)
    session.commit()
    user = session.query(User).filter_by(email = login_session['email']).one()
    return user.id


if __name__ == '__main__':
    app.secret_key = 'secret_shmecret'
    app.debug = True
    app.run(host='0.0.0.0', port=8080)

