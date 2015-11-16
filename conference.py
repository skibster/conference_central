#!/usr/bin/env python

"""
conference.py -- Udacity conference server-side Python App Engine API;
    uses Google Cloud Endpoints

$Id: conference.py,v 1.25 2014/05/24 23:42:19 wesc Exp wesc $

created by wesc on 2014 apr 21

"""

from datetime import datetime

import endpoints
from protorpc import messages
from protorpc import message_types
from protorpc import remote

from google.appengine.api import memcache
from google.appengine.api import taskqueue
from google.appengine.ext import ndb

from models import ConflictException
from models import Profile
from models import ProfileMiniForm
from models import ProfileForm
from models import StringMessage
from models import BooleanMessage
from models import Conference
from models import ConferenceForm
from models import ConferenceForms
from models import ConferenceQueryForm
from models import ConferenceQueryForms
from models import TeeShirtSize
from models import Session
from models import SessionForm
from models import SessionForms
from models import SessionsByType
from models import SessionsBySpeaker
from models import AddSessionToWishlist
from models import FindSessionByDatewithStartTimeRange
from models import SessionsBySpeakerOnSpecificDate
from models import Speaker
from models import SpeakerForm
from models import SpeakerForms

from settings import WEB_CLIENT_ID
from settings import ANDROID_CLIENT_ID
from settings import IOS_CLIENT_ID
from settings import ANDROID_AUDIENCE

from utils import getUserId

__author__ = 'wesc+api@google.com (Wesley Chun)'

EMAIL_SCOPE = endpoints.EMAIL_SCOPE
API_EXPLORER_CLIENT_ID = endpoints.API_EXPLORER_CLIENT_ID
MEMCACHE_ANNOUNCEMENTS_KEY = "RECENT_ANNOUNCEMENTS"
MEMCACHE_FEATURED_SPEAKER_KEY = "FEATURED_SPEAKER"
ANNOUNCEMENT_TPL = ('Last chance to attend! The following conferences '
                    'are nearly sold out: %s')
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

DEFAULTS = {
    "city": "Default City",
    "maxAttendees": 0,
    "seatsAvailable": 0,
    "topics": ["Default", "Topic"],
}

OPERATORS = {
            'EQ':   '=',
            'GT':   '>',
            'GTEQ': '>=',
            'LT':   '<',
            'LTEQ': '<=',
            'NE':   '!='
            }

FIELDS = {
         'CITY': 'city',
         'TOPIC': 'topics',
         'MONTH': 'month',
         'MAX_ATTENDEES': 'maxAttendees',
         }

CONF_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1, required=True),
)

CONF_POST_REQUEST = endpoints.ResourceContainer(
    ConferenceForm,
    websafeConferenceKey=messages.StringField(1),
)

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -


@endpoints.api(name='conference', version='v1', audiences=[ANDROID_AUDIENCE],
               allowed_client_ids=[WEB_CLIENT_ID, API_EXPLORER_CLIENT_ID,
               ANDROID_CLIENT_ID, IOS_CLIENT_ID],
               scopes=[EMAIL_SCOPE])
class ConferenceApi(remote.Service):
    """Conference API v0.1"""

# - - - Conference objects - - - - - - - - - - - - - - - - -

    def _copyConferenceToForm(self, conf, displayName):
        """Copy relevant fields from Conference to ConferenceForm."""
        cf = ConferenceForm()
        for field in cf.all_fields():
            if hasattr(conf, field.name):
                # convert Date to date string; just copy others
                if field.name.endswith('Date'):
                    setattr(cf, field.name, str(getattr(conf, field.name)))
                else:
                    setattr(cf, field.name, getattr(conf, field.name))
            elif field.name == "websafeKey":
                setattr(cf, field.name, conf.key.urlsafe())
        if displayName:
            setattr(cf, 'organizerDisplayName', displayName)
        cf.check_initialized()
        return cf

    def _createConferenceObject(self, request):
        """Create or update Conference object,
        returning ConferenceForm/request."""
        # preload necessary data items
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        if not request.name:
            raise endpoints.BadRequestException(
                "Conference 'name' field required")

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name)
                for field in request.all_fields()}
        del data['websafeKey']
        del data['organizerDisplayName']

        # add default values for those missing
        # (both data model & outbound Message)
        for df in DEFAULTS:
            if data[df] in (None, []):
                data[df] = DEFAULTS[df]
                setattr(request, df, DEFAULTS[df])

        # convert dates from strings to Date objects;
        # set month based on start_date
        if data['startDate']:
            data['startDate'] = datetime.strptime(
                data['startDate'][:10], "%Y-%m-%d").date()
            data['month'] = data['startDate'].month
        else:
            data['month'] = 0
        if data['endDate']:
            data['endDate'] = datetime.strptime(
                data['endDate'][:10], "%Y-%m-%d").date()

        # set seatsAvailable to be same as maxAttendees on creation
        if data["maxAttendees"] > 0:
            data["seatsAvailable"] = data["maxAttendees"]
        # generate Profile Key based on user ID and Conference
        # ID based on Profile key get Conference key from ID
        p_key = ndb.Key(Profile, user_id)
        c_id = Conference.allocate_ids(size=1, parent=p_key)[0]
        c_key = ndb.Key(Conference, c_id, parent=p_key)
        data['key'] = c_key
        data['organizerUserId'] = request.organizerUserId = user_id

        # create Conference, send email to organizer confirming
        # creation of Conference & return (modified) ConferenceForm
        Conference(**data).put()
        taskqueue.add(params={'email': user.email(),
                      'conferenceInfo': repr(request)},
                      url='/tasks/send_confirmation_email')

        return request

    @ndb.transactional()
    def _updateConferenceObject(self, request):
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name)
                for field in request.all_fields()}

        # update existing conference
        try:
            conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        except:
            conf = None
        # check that conference exists
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found for key: %s' \
                % request.websafeConferenceKey)

        # check that user is owner
        if user_id != conf.organizerUserId:
            raise endpoints.ForbiddenException(
                'Only the owner can update the conference.')

        # Not getting all the fields, so don't create a new object; just
        # copy relevant fields from ConferenceForm to Conference object
        for field in request.all_fields():
            data = getattr(request, field.name)
            # only copy fields where we get data
            if data not in (None, []):
                # special handling for dates (convert string to Date)
                if field.name in ('startDate', 'endDate'):
                    data = datetime.strptime(data, "%Y-%m-%d").date()
                    if field.name == 'startDate':
                        conf.month = data.month
                # write to Conference object
                setattr(conf, field.name, data)
        conf.put()
        prof = ndb.Key(Profile, user_id).get()
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))

    @endpoints.method(ConferenceForm, ConferenceForm, path='conference',
                      http_method='POST', name='createConference')
    def createConference(self, request):
        """Create new conference."""
        return self._createConferenceObject(request)

    @endpoints.method(CONF_POST_REQUEST, ConferenceForm,
                      path='conference/{websafeConferenceKey}',
                      http_method='PUT', name='updateConference')
    def updateConference(self, request):
        """Update conference w/provided fields & return w/updated info."""
        return self._updateConferenceObject(request)

    @endpoints.method(CONF_GET_REQUEST, ConferenceForm,
                      path='conference/{websafeConferenceKey}',
                      http_method='GET', name='getConference')
    def getConference(self, request):
        """Return requested conference (by websafeConferenceKey)."""
        # get Conference object from request; bail if not found
        try:
            conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        except:
            conf = None

        if not conf:
            raise endpoints.NotFoundException(
                'No conference found for key: %s' \
                % request.websafeConferenceKey)
        prof = conf.key.parent().get()
        # return ConferenceForm
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))

    @endpoints.method(message_types.VoidMessage, ConferenceForms,
                      path='getConferencesCreated',
                      http_method='POST', name='getConferencesCreated')
    def getConferencesCreated(self, request):
        """Return conferences created by user."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # create ancestor query for all key matches for this user
        confs = Conference.query(ancestor=ndb.Key(Profile, user_id))
        prof = ndb.Key(Profile, user_id).get()
        # return set of ConferenceForm objects per Conference
        return ConferenceForms(
            items=[self._copyConferenceToForm(
                conf, getattr(prof, 'displayName')) for conf in confs])

    def _getQuery(self, request):
        """Return formatted query from the submitted filters."""
        q = Conference.query()
        inequality_filter, filters = self._formatFilters(request.filters)

        # If exists, sort on inequality filter first
        if not inequality_filter:
            q = q.order(Conference.name)
        else:
            q = q.order(ndb.GenericProperty(inequality_filter))
            q = q.order(Conference.name)

        for filtr in filters:
            if filtr["field"] in ["month", "maxAttendees"]:
                filtr["value"] = int(filtr["value"])
            formatted_query = ndb.query.FilterNode(
                filtr["field"], filtr["operator"], filtr["value"])
            q = q.filter(formatted_query)
        return q

    def _formatFilters(self, filters):
        """Parse, check validity and format user supplied filters."""
        formatted_filters = []
        inequality_field = None

        for f in filters:
            filtr = {field.name: getattr(f, field.name)
                     for field in f.all_fields()}

            try:
                filtr["field"] = FIELDS[filtr["field"]]
                filtr["operator"] = OPERATORS[filtr["operator"]]
            except KeyError:
                raise endpoints.BadRequestException(
                    "Filter contains invalid field or operator.")

            # Every operation except "=" is an inequality
            if filtr["operator"] != "=":
                # check if inequality operation has been used in previous
                # filters disallow the filter if inequality was performed
                # on a different field before track the field on which the
                # inequality operation is performed
                if inequality_field and inequality_field != filtr["field"]:
                    raise endpoints.BadRequestException(
                        "Inequality filter is allowed on only one field.")
                else:
                    inequality_field = filtr["field"]

            formatted_filters.append(filtr)
        return (inequality_field, formatted_filters)

    @endpoints.method(ConferenceQueryForms, ConferenceForms,
                      path='queryConferences',
                      http_method='POST',
                      name='queryConferences')
    def queryConferences(self, request):
        """Query for conferences."""
        conferences = self._getQuery(request)

        # need to fetch organiser displayName from profiles
        # get all keys and use get_multi for speed
        organisers = [(ndb.Key(Profile, conf.organizerUserId))
                      for conf in conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return individual ConferenceForm object per Conference
        return ConferenceForms(
                items=[self._copyConferenceToForm(
                      conf, names[conf.organizerUserId]) for conf in
                      conferences])


# - - - Profile objects - - - - - - - - - - - - - - - - - - -

    def _copyProfileToForm(self, prof):
        """Copy relevant fields from Profile to ProfileForm."""
        # copy relevant fields from Profile to ProfileForm
        pf = ProfileForm()
        for field in pf.all_fields():
            if hasattr(prof, field.name):
                # convert t-shirt string to Enum; just copy others
                if field.name == 'teeShirtSize':
                    setattr(pf, field.name, getattr(
                            TeeShirtSize, getattr(prof, field.name)))
                else:
                    setattr(pf, field.name, getattr(prof, field.name))
        pf.check_initialized()
        return pf

    def _getProfileFromUser(self):
        """Return user Profile from datastore, creating new one
        if non-existent."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        # get Profile from datastore
        user_id = getUserId(user)
        p_key = ndb.Key(Profile, user_id)
        profile = p_key.get()
        # create new Profile if not there
        if not profile:
            profiles = Profile(key=p_key,
                               displayName=user.nickname(),
                               mainEmail=user.email(),
                               teeShirtSize=str(TeeShirtSize.NOT_SPECIFIED),)
            profile.put()

        return profile      # return Profile

    def _doProfile(self, save_request=None):
        """Get user Profile and return to user, possibly updating it first."""
        # get user Profile
        prof = self._getProfileFromUser()

        # if saveProfile(), process user-modifyable fields
        if save_request:
            for field in ('displayName', 'teeShirtSize'):
                if hasattr(save_request, field):
                    val = getattr(save_request, field)
                    if val:
                        setattr(prof, field, str(val))
                        # if field == 'teeShirtSize':
                        #    setattr(prof, field, str(val).upper())
                        # else:
                        #    setattr(prof, field, val)
                        prof.put()

        # return ProfileForm
        return self._copyProfileToForm(prof)

    @endpoints.method(message_types.VoidMessage, ProfileForm,
                      path='profile', http_method='GET', name='getProfile')
    def getProfile(self, request):
        """Return user profile."""
        return self._doProfile()

    @endpoints.method(ProfileMiniForm, ProfileForm,
                      path='profile', http_method='POST', name='saveProfile')
    def saveProfile(self, request):
        """Update & return user profile."""
        return self._doProfile(request)


# - - - Announcements - - - - - - - - - - - - - - - - - - - -

    @staticmethod
    def _cacheAnnouncement():
        """Create Announcement & assign to memcache; used by
        memcache cron job & putAnnouncement().
        """
        confs = Conference.query(ndb.AND(
            Conference.seatsAvailable <= 5,
            Conference.seatsAvailable > 0)
        ).fetch(projection=[Conference.name])

        if confs:
            # If there are almost sold out conferences,
            # format announcement and set it in memcache
            announcement = ANNOUNCEMENT_TPL % (
                ', '.join(conf.name for conf in confs))
            memcache.set(MEMCACHE_ANNOUNCEMENTS_KEY, announcement)
        else:
            # If there are no sold out conferences,
            # delete the memcache announcements entry
            announcement = ""
            memcache.delete(MEMCACHE_ANNOUNCEMENTS_KEY)

        return announcement

    @staticmethod
    def _setFeaturedSpeaker(conf_key, speaker_key):
        """Create Featured Speaker text and assign to memcache;
           used by getFeaturedSpeaker().
        """
        conf = ndb.Key(urlsafe=conf_key).get()
        speaker = ndb.Key(urlsafe=speaker_key).get()

        q = Session.query(ancestor=conf.key)
        q = q.filter(Session.speaker == speaker.key).fetch()

        # if number of sessions for this speaker is > 1
        # then this is the featured speaker
        if len(q) > 1:
            # format announcement and set it in memcache
            featured_speaker = "Our featured speaker for %s is: %s %s!" \
                % (conf.name, speaker.firstName, speaker.lastName)
            memcache.set(MEMCACHE_FEATURED_SPEAKER_KEY, featured_speaker)
        else:
            featured_speaker = None
        return featured_speaker

    @endpoints.method(message_types.VoidMessage, StringMessage,
                      path='conference/announcement/get',
                      http_method='GET', name='getAnnouncement')
    def getAnnouncement(self, request):
        """Return Announcement from memcache."""
        return StringMessage(data=memcache.get(
                             MEMCACHE_ANNOUNCEMENTS_KEY) or "")

    @endpoints.method(message_types.VoidMessage, StringMessage,
                      path='conference/featured_speaker/get',
                      http_method='GET', name='getFeaturedSpeaker')
    def getAnnouncement(self, request):
        """Return Featured Speaker from memcache."""
        return StringMessage(data=memcache.get(
                             MEMCACHE_FEATURED_SPEAKER_KEY) or "")

# - - - Registration - - - - - - - - - - - - - - - - - - - -

    @ndb.transactional(xg=True)
    def _conferenceRegistration(self, request, reg=True):
        """Register or unregister user for selected conference."""
        retval = None
        prof = self._getProfileFromUser()  # get user Profile

        # check if conf exists given websafeConfKey
        # get conference; check that it exists
        wsck = request.websafeConferenceKey
        try:
            conf = ndb.Key(urlsafe=wsck).get()
        except:
            conf = None

        if not conf:
            raise endpoints.NotFoundException(
                'No conference found for key: %s' % wsck)

        # register
        if reg:
            # check if user already registered otherwise add
            if wsck in prof.conferenceKeysToAttend:
                raise ConflictException(
                    "You have already registered for this conference")

            # check if seats avail
            if conf.seatsAvailable <= 0:
                raise ConflictException(
                    "There are no seats available.")

            # register user, take away one seat
            prof.conferenceKeysToAttend.append(wsck)
            conf.seatsAvailable -= 1
            retval = True

        # unregister
        else:
            # check if user already registered
            if wsck in prof.conferenceKeysToAttend:

                # unregister user, add back one seat
                prof.conferenceKeysToAttend.remove(wsck)
                conf.seatsAvailable += 1
                retval = True
            else:
                retval = False

        # write things back to the datastore & return
        prof.put()
        conf.put()
        return BooleanMessage(data=retval)

    @endpoints.method(message_types.VoidMessage, ConferenceForms,
                      path='conferences/attending',
                      http_method='GET', name='getConferencesToAttend')
    def getConferencesToAttend(self, request):
        """Get list of conferences that user has registered for."""
        prof = self._getProfileFromUser()  # get user Profile
        conf_keys = [ndb.Key(urlsafe=wsck) for wsck in
                     prof.conferenceKeysToAttend]
        conferences = ndb.get_multi(conf_keys)

        # get organizers
        organisers = [ndb.Key(Profile, conf.organizerUserId) for
                      conf in conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return set of ConferenceForm objects per Conference
        return ConferenceForms(items=[self._copyConferenceToForm(
                               conf, names[conf.organizerUserId]) for
                               conf in conferences])

    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
                      path='conference/{websafeConferenceKey}',
                      http_method='POST', name='registerForConference')
    def registerForConference(self, request):
        """Register user for selected conference."""
        return self._conferenceRegistration(request)

    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
                      path='conference/{websafeConferenceKey}',
                      http_method='DELETE', name='unregisterFromConference')
    def unregisterFromConference(self, request):
        """Unregister user for selected conference."""
        return self._conferenceRegistration(request, reg=False)

    @endpoints.method(message_types.VoidMessage, ConferenceForms,
                      path='filterPlayground',
                      http_method='GET', name='filterPlayground')
    def filterPlayground(self, request):
        """Filter Playground"""
        q = Conference.query()
        # field = "city"
        # operator = "="
        # value = "London"
        # f = ndb.query.FilterNode(field, operator, value)
        # q = q.filter(f)
        q = q.filter(Conference.city == "London")
        q = q.filter(Conference.topics == "Medical Innovations")
        q = q.filter(Conference.month == 6)

        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, "") for conf in q]
        )

# - - - Sessions - - - - - - - - - - - - - - - - - - - -
    def _copySessionToForm(self, sess):
        """Copy relevant fields from Session to SessionForm."""
        sf = SessionForm()
        for field in sf.all_fields():
            if hasattr(sess, field.name):
                # Convert Date to string
                # Convert Time to string in HH:MM only
                # else convert others as is
                if field.name.endswith('date'):
                    setattr(sf, field.name, str(getattr(sess, field.name)))
                elif field.name.endswith('Time'):
                    setattr(sf, field.name,
                            str(getattr(sess, field.name).strftime("%H:%M")))
                else:
                    setattr(sf, field.name, getattr(sess, field.name))
            elif field.name == "sessionWebSafeKey":
                setattr(sf, field.name, sess.key.urlsafe())
            elif field.name == "speakerName":
                try:
                    speaker = sess.speaker.get()
                    speakerName = "%s %s" % (getattr(speaker, "firstName"),
                                             getattr(speaker, "lastName"))
                    setattr(sf, 'speakerName', speakerName)
                except:
                    pass
        sf.check_initialized()
        return sf

    def _createSessionObject(self, request):
        """Create a Session, returning SessionForm/request."""
        # preload necessary data items
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        if not request.name:
            raise endpoints.BadRequestException(
                "Session 'name' field required")

        data = {field.name: getattr(request, field.name) for
                field in request.all_fields()}

        # get existing conference using web safe key
        try:
            conf = ndb.Key(urlsafe=data['conferenceWebSafeKey']).get()
        except:
            conf = None

        # check that conference exists
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found for key: %s' \
                % data['conferenceWebSafeKey'])

        if user_id != conf.organizerUserId:
            raise endpoints.ForbiddenException(
                'Only the Conference owner can create sessions.')

        # get speaker using web safe key
        try:
            speaker = ndb.Key(urlsafe=data['speakerWebSafeKey']).get()
            data['speaker'] = speaker.key
            # check parent of key to confirm Speaker is owned by user
            speaker_parent = speaker.key.parent().pairs()
            speaker_parent = speaker_parent[0][1]
        except:
            speaker = None
            speaker_parent = None

        if user_id != speaker_parent:
            raise endpoints.ForbiddenException(
                'Only the Speaker owner can use this speaker.')

        # convert dates/times from strings to Date/Time objects
        if data['date']:
            data['date'] = datetime.strptime(
                           data['date'][:10], "%Y-%m-%d").date()
        if data['startTime']:
            data['startTime'] = datetime.strptime(
                                data['startTime'][:5], "%H:%M").time()

        # generate Session ID based on Conf key, get Session key from ID
        session_id = Session.allocate_ids(size=1, parent=conf.key)[0]
        session_key = ndb.Key(Session, session_id, parent=conf.key)
        data['key'] = session_key
        del data['conferenceWebSafeKey']
        del data['sessionWebSafeKey']
        del data['speakerName']
        del data['speakerWebSafeKey']

        # create Session
        Session(**data).put()

        # add a task to see if this new session creates a featured speaker
        taskqueue.add(params={'websafeConferenceKey': conf.key.urlsafe(),
                      'websafeSpeakerKey': speaker.key.urlsafe()},
                      url='/tasks/set_featured_speaker',
                      method='GET')

        return request

    def _SessionToWishList(self, request, add=True):
        """Register session to user's wishlist."""
        retval = None
        prof = self._getProfileFromUser()  # get user Profile

        # check if session exists given websafeConfKey
        # get session; check that it exists
        session_wsck = request.sessionWebSafeKey

        try:
            session = ndb.Key(urlsafe=session_wsck).get()
        except:
            session = None

        if not session:
            raise endpoints.NotFoundException(
                'No session found for key: %s' % session_wsck)

        # add
        if add:
            # check if user already has session in wishlist
            if session_wsck in prof.sessionKeysToAttend:
                raise ConflictException(
                    "You already have this session on your wishlist.")

            # add session to wishlist
            prof.sessionKeysToAttend.append(session_wsck)
            retval = True

        # remove
        else:
            # check if user already has session in wishlist
            if session_wsck in prof.sessionKeysToAttend:

                # remove session from wishlist
                prof.sessionKeysToAttend.remove(session_wsck)
                retval = True
            else:
                retval = False

        # write things back to the datastore & return
        prof.put()
        return BooleanMessage(data=retval)

    @endpoints.method(SessionForm, SessionForm,
                      path='conference/create_session',
                      http_method='POST', name='createSession')
    def createSession(self, request):
        """Create new conference session."""
        return self._createSessionObject(request)

    @endpoints.method(CONF_GET_REQUEST, SessionForms,
                      path='conference/sessions',
                      http_method='GET', name='getConferenceSessions')
    def getConferenceSessions(self, request):
        """Return sessions for a Conference (by websafeConferenceKey)."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        # user_id = getUserId(user)
        wsck = request.websafeConferenceKey
        try:
            conf = ndb.Key(urlsafe=wsck).get()
        except:
            conf = None

        if not conf:
            raise endpoints.NotFoundException(
                'No conference found for key: %s' % wsck)

        # create ancestor query for all key matches for this conference
        sessions = Session.query(ancestor=conf.key)

        # return set of SessionForm objects for conference
        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions]
        )

    @endpoints.method(SessionsByType, SessionForms,
                      path='conference/sessions_by_type',
                      http_method='GET', name='getConferenceSessionsByType')
    def getConferenceSessionsByType(self, request):
        """Return sessions for a Conference by Type."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        # user_id = getUserId(user)
        wsck = request.websafeConferenceKey
        try:
            conf = ndb.Key(urlsafe=wsck).get()
        except:
            conf = None

        if not conf:
            raise endpoints.NotFoundException(
                'No conference found for key: %s' % wsck)

        # create ancestor query for all key matches for this conference
        # then filter on typeOfSession
        typeOfSession = request.typeOfSession
        sessions = Session.query(ancestor=conf.key)
        sessions = sessions.filter(Session.typeOfSession == typeOfSession)

        # return set of SessionForm objects per Conference
        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions]
        )

    @endpoints.method(SessionsBySpeaker, SessionForms,
                      path='conference/sessions_by_speaker',
                      http_method='GET', name='getSessionsBySpeaker')
    def getConferenceSessionsBySpeaker(self, request):
        """Return Conference sessions by Speaker."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        # user_id = getUserId(user)

        sp_lastName = request.lastName
        sp_firstName = request.firstName

        if sp_firstName:
            # find by first and last name
            speaker = Speaker.query(ndb.AND(
                Speaker.lastName == sp_lastName,
                Speaker.firstName == sp_firstName))
        else:
            # find by last name only
            speaker = Speaker.query(Speaker.lastName == sp_lastName)

        speaker_keys = [sp.key for sp in speaker]

        # iterate over each key finding all sessions
        all_sessions = []
        for sp_k in speaker_keys:
            sessions = Session.query(Session.speaker == sp_k)
            for s in sessions:
                all_sessions.append(s)

        # return list of sessions that match each of the speaker_keys
        return SessionForms(
            items=[self._copySessionToForm(sess) for sess in all_sessions]
        )

    @endpoints.method(AddSessionToWishlist, BooleanMessage,
                      path='session/add_to_wishlist',
                      http_method='POST', name='addSessionToWishlist')
    def addSessionToWishlist(self, request):
        """Add session to user's wishlist."""
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        # user_id = getUserId(user)
        return self._SessionToWishList(request)

    @endpoints.method(AddSessionToWishlist, BooleanMessage,
                      path='session/remove_from_wishlist',
                      http_method='DELETE', name='removeSessionFromWishlist')
    def removeSessionFromWishlist(self, request):
        """Remove session to user's wishlist."""
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        # user_id = getUserId(user)
        return self._SessionToWishList(request, add=False)

    @endpoints.method(message_types.VoidMessage, SessionForms,
                      path='sessions/get_wishlist',
                      http_method='GET', name='getSessionsInWishlist')
    def getSessionsInWishlist(self, request):
        """Get list of sessions that user has on their wishlist."""
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        # user_id = getUserId(user)
        prof = self._getProfileFromUser()  # get user Profile
        session_keys = [ndb.Key(urlsafe=wsck) for wsck
                        in prof.sessionKeysToAttend]
        sessions = ndb.get_multi(session_keys)

        # return set of session objects in wishlist
        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions]
        )

    @endpoints.method(FindSessionByDatewithStartTimeRange, SessionForms,
                      path='session/find_by_date_and_start_time_range',
                      http_method='GET',
                      name='FindSessionByDatewithStartTimeRange')
    def FindSessionByDatewithStartTimeRange(self, request):
        """Find Sessions By Date with Start Time Range"""
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        # user_id = getUserId(user)

        sessions = Session.query()

        theStartTime = datetime.strptime(
                       request.startTimeRangeBeginning, "%H:%M").time()
        theEndTime = datetime.strptime(
                     request.startTimeRangeEnding, "%H:%M").time()
        theDate = datetime.strptime(request.conferenceDate, "%Y-%m-%d").date()

        sessions = sessions.filter(Session.startTime >= theStartTime)
        sessions = sessions.filter(Session.startTime <= theEndTime)
        sessions = sessions.filter(Session.date == theDate)

        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions]
        )

    @endpoints.method(SessionsBySpeakerOnSpecificDate, SessionForms,
                      path='session/find_by_speaker_on_specific_date',
                      http_method='GET',
                      name='SessionsBySpeakerOnSpecificDate')
    def SessionsBySpeakerOnSpecificDate(self, request):
        """Return Conference sessions by Speaker on a specific date."""

        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        # user_id = getUserId(user)

        sp_lastName = request.lastName
        sp_firstName = request.firstName
        theDate = datetime.strptime(request.conferenceDate, "%Y-%m-%d").date()

        if sp_firstName:
            # find by first and last name
            speaker = Speaker.query(ndb.AND(
                Speaker.lastName == sp_lastName,
                Speaker.firstName == sp_firstName))
        else:
            # find by last name only
            speaker = Speaker.query(Speaker.lastName == sp_lastName)

        speaker_keys = [sp.key for sp in speaker]

        # iterate over each key finding all sessions
        all_sessions = []
        for sp_k in speaker_keys:
            sessions = Session.query(ndb.AND(
                Session.speaker == sp_k,
                Session.date == theDate))
            for s in sessions:
                all_sessions.append(s)

        # return list of sessions that match each of the speaker_keys
        return SessionForms(
            items=[self._copySessionToForm(sess) for sess in all_sessions]
        )

    @endpoints.method(message_types.VoidMessage, SessionForms,
                      path='session/nonWorkshop_Sessions_Before_7pm',
                      http_method='GET', name='NonWorkshopSessionsBefore7pm')
    def NonWorkshopSessionsBefore7pm(self, request):
        """Return Non-Workshop Sessions Before 7pm."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        # user_id = getUserId(user)

        theStartTime = datetime.strptime("19:00", "%H:%M").time()

        # idea from reading answers from Tim Hoffman
        # (http://stackoverflow.com/users/1201324/tim-hoffman)
        # and Brent Washburne
        # (http://stackoverflow.com/users/584846/brent-washburne)
        # specifically Brent's answer here:
        # https://stackoverflow.com/questions/33549573/combining-results-of-multiple-ndb-inequality-queries

        # create two separate inequality queries and get the keys from each
        # then use set.intersection method to get the
        # intersection of the two sets
        query1 = Session.query(Session.typeOfSession != "Workshop").fetch(
                               keys_only=True)
        query2 = Session.query(Session.startTime < theStartTime).fetch(
                               keys_only=True)
        sessions = ndb.get_multi(set(query1).intersection(query2))

        # return set of SessionForm objects per Conference
        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions]
        )


# - - - Speaker - - - - - - - - - - - - - - - - - - - -

    def _copySpeakerToForm(self, speak):
        """Copy relevant fields from Speaker to SpeakerForm."""
        sp = SpeakerForm()
        for field in sp.all_fields():
            if hasattr(speak, field.name):
                setattr(sp, field.name, getattr(speak, field.name))
            elif field.name == "speakerWebSafeKey":
                setattr(sp, field.name, speak.key.urlsafe())
        sp.check_initialized()
        return sp

    def _createSpeakerObject(self, request):
        """Create a Speaker object."""
        # preload necessary data items
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        if not request.firstName:
            raise endpoints.BadRequestException(
                "Speaker 'firstName' field required")
        if not request.lastName:
            raise endpoints.BadRequestException(
                "Speaker 'lastName' field required")

        # copy SpeakerForm Message into dict
        data = {field.name: getattr(request, field.name) for field
                in request.all_fields()}

        # generate Profile Key based on user ID and Speaker
        # ID based on Profile key get Speaker key from ID
        p_key = ndb.Key(Profile, user_id)
        speaker_id = Speaker.allocate_ids(size=1, parent=p_key)[0]
        speaker_key = ndb.Key(Speaker, speaker_id, parent=p_key)
        data['key'] = speaker_key
        del data['speakerWebSafeKey']

        # creation Speaker entity
        Speaker(**data).put()

        return request

    @endpoints.method(SpeakerForm, SpeakerForm, path='speaker/create_speaker',
                      http_method='POST', name='createSpeaker')
    def createSpeaker(self, request):
        """Create new speaker."""
        return self._createSpeakerObject(request)

    @endpoints.method(message_types.VoidMessage, SpeakerForms,
                      path='speaker/speakers',
                      http_method='GET', name='getSpeakersCreated')
    def getSpeakersCreated(self, request):
        """Return speakers created by user."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # create ancestor query for all key matches for this user
        speakers = Speaker.query(ancestor=ndb.Key(Profile, user_id))

        # return set of Speaker objects
        return SpeakerForms(
            items=[self._copySpeakerToForm(speaker) for speaker in speakers]
        )


api = endpoints.api_server([ConferenceApi])  # register API
