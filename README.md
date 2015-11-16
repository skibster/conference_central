# Conference Central

App Engine application for the Udacity training course.

## Products
- [App Engine][1]

## Language
- [Python][2]

## APIs
- [Google Cloud Endpoints][3]

## Setup Instructions
1. Update the value of `application` in `app.yaml` to the app ID you
   have registered in the App Engine admin console and would like to use to host
   your instance of this sample.
1. Update the values at the top of `settings.py` to
   reflect the respective client IDs you have registered in the
   [Developer Console][4].
1. Update the value of CLIENT_ID in `static/js/app.js` to the Web client ID
1. (Optional) Mark the configuration files as unchanged as follows:
   `$ git update-index --assume-unchanged app.yaml settings.py static/js/app.js`
1. Run the app with the devserver using `dev_appserver.py DIR`, and ensure it's running by visiting your local server's address (by default [localhost:8080][5].)
1. (Optional) Generate your client library(ies) with [the endpoints tool][6].
1. Deploy your application.

## Application Data Model
This application contains the following data models:

1. **Profile** - This model houses information about the logged in user. Certain functions like creating speakers and sessions for conferences is governed by which user created the data object. The following data is housed in the Profile model:
    * *displayName* - the user specified name to display in the application.
    * *mainEmail* - the user's email as determined by Google authentication.
    * *teeShirtSize* - the user's preferred t-shirt size when receiving conference swag.
    * *conferenceKeysToAttend* - a list of web safe conference keys of conferences the user will be attending.
    * *sessionKeysToAttend* - a list of web safe session keys of sessions the user will be attending.
2. **Conference** - This model houses information about individual conferences that are entered into the application. Conferencees are created under specific user's profiles. Only users who create conferences can modify them and add sessions to them. Once a conference is created, it will be assigned a webSafeConferenceKey which can be used in the API to reference the conference. The following data is housed in the Conference model:
    * *name* - the name of the conference. This is a *required* field when creating conferences.
    * *description* - this is a description of the conference.
    * *organizerUserId* - this is the user who created the conference. Only the user who created the conference can modify it or add sessions to it.
    * *topics* - a list of topics to be covered in the conference.
    * *city* - the city where the conference will be held.
    * *startDate* - the start date of the conference. Dates are entered in YYYY-MM-DD format.
    * *month* - an integer representing the month the conference will be held.
    * *endDate* - the end date of the conference. Dates are entered in YYYY-MM-DD format.
    * *maxAttendees* - this is the maxiumum number of users who can attend the conference.
    * *seatsAvailable* - this is the remaining number of seats available to attend the conference.
3. **Speaker** - This model houses information about speakers who will present sessions at the conference. Only users who create the speakers can use them and only for their conferences (the speaker is a child of the Profile user). This allows each logged in user to manage their own set of speakers for all of their conferences. Speakers should be defined before creating sessions if you want to associate a speaker with a session. Once a speaker is created, it will be assigned a speakerWebSafeKey which can be used in the API to reference the speaker. The following data is housed in the Speaker model:
    * *firstName* - the first name of the speaker. This is a required field.
    * *lastName* - the last name of the speaker. This is a required field.
    * *email* - the email address of the speaker.
    * *phoneNumber* - the phone number of the speaker.
    * *biography* - the biography of the speaker.
    * companyName* - the company the speaker works for or represents.
4. **Sessions** - This model houses information about the individual sessions that will be held during the conference. Only users who create the conference can add sessions to the conference (the session is a child of the conference). This allows each logged in user to create and manage their own sessions for their conference. Once a session is created, it will be assigned a sessionWebSafeKey which can be used in the API to reference the session. The following data is housed in the Session model:
    * *date* the date of the session. This is a required field. Dates are entered in YYYY-MM-DD format.
    * *duration* - the number of minutes the session will last (e.g., 120 = a 2 hour session).
    * *highlights* - the highlights of the session.
    * *name* - the name of the session. This is a required field.
    * *speaker* - this is the speakerWebSafeKey of the speaker presenting this session.
    * *startTime* - this it the time the session begins. This is a required field. The time should be entered in 24 hour notation (e.g., 14:00 = 2:00pm).
    *  *typeOfSession* - this is a list of keywords to help users search for sessions (e.g., "Lecture", "Workshop", "Keynote", etc).

## Application Programming Interface (API)
This application is designed with a robust Web Service API to perform all the functionality of the front end system through web service methods. Endpoints for this installation of Conference Central can be accessed [here][7]

The following endpoints are available to users:
### Profile
  * getProfile - get user's profile
  * saveProfile - modify user's profile and save

### Conference
  * createConference - create a new conference
  * filterPlayground - hard coded filter routine (for development only)
  * getConference - get a particular conference using the webSafeConferenceKey
  * getConferencesCreated - get a list of conferences created by the user
  * getConferencesToAttend - get a list of conferences the user will attend
  * queryConferences - create filter(s) to query for various conferences
  * registerForConference - register for a conference using the webSafeConferenceKey
  * unregisterForConference - unregister for a conference using the webSafeConferenceKey
  * updateConference - update a conference with new data fields using the webSafeConferenceKey

### Speaker
  * createSpeaker - creata a speaker who will be referenced as a speaker for a particular session
  * getFeaturedSpeaker - when the same speaker speaks in more than one session at a conference, that speaker is considered the featured speaker. Featured speaker is generated using a task queue at the time sessions are created (**Rubric: Task 4**)
  * getSpeakersCreated - get a list of speakers the user has created

### Session
  * addSessionToWishlist - add a particular session to the user's wishlist using the sessionWebSafeKey
  * createSession - create a session for a particular conference using the conferenceWebSafe Key and speakerWebSafeKey
  * findSessionByDatewithStartTimeRange - get a list of sessions based on a date and a range of time (**Rubric: Task 3 additional query**)
  * getConferenceSessions - get a list of sessions for a particular conference using the webSafeConferenceKey
  * getConferenceSessionsByType - get a list of sessions for a type of session for a particular conference using the webSafeConferenceKey
  * getSessionsBySpeaker - get a list of sessions by speaker's last name or first name and last name
  * getSessionsInWishlist - get a list of sessions the user is wishing to attend
  * nonWorkshopSessionsBefore7pm - get a list of non-workshop type sessions that start before 7pm. (**Rubric: Task 3 query problem**: This query presents a problem because it requires two inequality filters in the same query. Normally this is not possible, however, it is possible to make two independent queries (one for non-workshop type sessions and another for sessions before 7pm) and then using Python set and intersection, find the entities that are common to each query).
  * sessionsBySpeakerOnSpecificDate - get a list of sessions based on a speaker's name and the date of their session (**Rubric: Task 3 additional query**)
  * removeSessionFromWishlist - remove a particular session from the user's wishlist using the sessionWebSafeKey


[1]: https://developers.google.com/appengine
[2]: http://python.org
[3]: https://developers.google.com/appengine/docs/python/endpoints/
[4]: https://console.developers.google.com/
[5]: https://localhost:8080/
[6]: https://developers.google.com/appengine/docs/python/endpoints/endpoints_tool
[7]: https://apis-explorer.appspot.com/apis-explorer/?base=https://rich-boulevard-109002.appspot.com/_ah/api#p/conference/v1/
