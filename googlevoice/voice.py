from conf import config
from util import *
import settings
import os

from appengine_util import URLOpener

if settings.DEBUG:
    import logging
    logging.basicConfig()
    log = logging.getLogger('PyGoogleVoice')
    log.setLevel(logging.DEBUG)
else:
    log = None

class Voice(object):
    """
    Main voice instance for interacting with the Google Voice service
    Handles login/logout and most of the baser HTTP methods
    """
    def __init__(self):
        self.opener = URLOpener()

        for name in settings.FEEDS:
            setattr(self, name, self.__get_xml_page(name))

    ######################
    # Some handy methods
    ######################  
    def special(self):
        """
        Returns special identifier for your session (if logged in)
        """
        if hasattr(self, '_special') and getattr(self, '_special'):
            return self._special

        try:
            try:
                regex = bytes("('_rnr_se':) '(.+)'", 'utf8')
            except TypeError:
                regex = bytes("('_rnr_se':) '(.+)'")
        except NameError:
            regex = r"('_rnr_se':) '(.+)'"

        try:
            log.debug("Getting special")

            response = self.__do_page('inbox')

            sp = re.search(regex, response.content).group(2)
        except AttributeError:
            sp = None
        self._special = sp
        return sp
    special = property(special)
    
    def login(self, email=None, passwd=None):
        """
        Login to the service using your Google Voice account
        Credentials will be propmpted for if not given as args or in the ``~/.gvoice`` config file
        """
        if hasattr(self, '_special') and getattr(self, '_special'):
            return self
        
        if email is None:
            email = config.email
        if email is None:
            raise NoCredentialsError
        
        if passwd is None:
            passwd = config.password
        if passwd is None:
            raise NoCredentialsError

        content = self.__do_page('login').content
        # holy hackjob
        galx = re.search(r"name=\"GALX\"\s+value=\"(.+)\"", content).group(1)
        self.__do_page('login', {'Email': email, 'Passwd': passwd, 'GALX': galx, 'PersistentCookie': 'yes', 'service': 'grandcentral' })

        #self.__do_page('login', {'Email': email, 'Passwd': passwd, 'continue': settings.LOGIN_CONTINUE })
        
        del email, passwd
        
        try:
            assert self.special
        except (AssertionError, AttributeError):
            raise LoginError

        return self
        
    def logout(self):
        """
        Logs out an instance and makes sure it does not still have a session
        """
        self.__do_page('logout')
        del self._special 
        assert self.special == None
        return self
        
    def call(self, outgoingNumber, forwardingNumber=None, phoneType=None, subscriberNumber=None):
        """
        Make a call to an ``outgoingNumber`` from your ``forwardingNumber`` (optional).
        If you pass in your ``forwardingNumber``, please also pass in the correct ``phoneType``
        """        
        if forwardingNumber is None:
            forwardingNumber = config.forwardingNumber
        if phoneType is None:
            phoneType = config.phoneType
            
        self.__validate_special_page('call', {
            'outgoingNumber': outgoingNumber,
            'forwardingNumber': forwardingNumber,
            'subscriberNumber': subscriberNumber or 'undefined',
            'phoneType': phoneType,
            'remember': '1'
        })
        
    __call__ = call
    
    def cancel(self, outgoingNumber=None, forwardingNumber=None):
        """
        Cancels a call matching outgoing and forwarding numbers (if given). 
        Will raise an error if no matching call is being placed
        """
        self.__validate_special_page('cancel', {
            'outgoingNumber': outgoingNumber or 'undefined',
            'forwardingNumber': forwardingNumber or 'undefined',
            'cancelType': 'C2C',
        })

    def phones(self):
        """
        Returns a list of ``Phone`` instances attached to your account.
        """
        return [Phone(self, data) for data in self.contacts['phones'].values()]
    phones = property(phones)

    def settings(self):
        """
        Dict of current Google Voice settings
        """
        return AttrDict(self.contacts['settings'])
    settings = property(settings)
    
    def send_sms(self, phoneNumber, text):
        """
        Send an SMS message to a given ``phoneNumber`` with the given ``text`` message
        """
        self.__validate_special_page('sms', {'phoneNumber': phoneNumber, 'text': text})

    def search(self, query):
        """
        Search your Google Voice Account history for calls, voicemails, and sms
        Returns ``Folder`` instance containting matching messages
        """
        return self.__get_xml_page('search', data='?q=%s' % quote(query))()
        
    def download(self, msg, adir=None):
        """
        Download a voicemail or recorded call MP3 matching the given ``msg``
        which can either be a ``Message`` instance, or a SHA1 identifier. 
        Saves files to ``adir`` (defaults to current directory). 
        Message hashes can be found in ``self.voicemail().messages`` for example. 
        Returns location of saved file.
        """
        from os import path,getcwd
        if isinstance(msg, Message):
            msg = msg.id
        assert is_sha1(msg), 'Message id not a SHA1 hash'
        if adir is None:
            adir = getcwd()
        try:
            response = self.__do_page('download', msg)
        except:
            raise DownloadError
        fn = path.join(adir, '%s.mp3' % msg)
        fo = open(fn, 'wb')
        fo.write(response.read())
        fo.close()
        return fn
    
    def contacts(self):
        """
        Partial data of your Google Account Contacts related to your Voice account.
        For a more comprehensive suite of APIs, check out http://code.google.com/apis/contacts/docs/1.0/developers_guide_python.html
        """
        if hasattr(self, '_contacts'):
            return self._contacts
        self._contacts = self.__get_xml_page('contacts')()
        return self._contacts
    contacts = property(contacts)


    ######################
    # Pagination
    ######################

    def get_page(self, feed, page, data=None, headers={}):
        """
        Hackish way of doing pagination
        """
        if feed.lower() not in settings.FEEDS:
            raise NoSuchFeedError

        if isinstance(data, dict):
            data.update({'page': "p%d" % page })
        elif isinstance(data, tuple):
            data += ('page', "p%d" % page)
        elif data is None:
            data = {'page': "p%d" % page}
        return self.__get_xml_page(feed, data, headers)

    ######################
    # Helper methods
    ######################

    def __do_page(self, page, data=None, headers={}, force_get=False):
        """
        Loads a page out of the settings and pass it on to urllib Request
        """
        page = page.upper()
        if isinstance(data, dict) or isinstance(data, tuple):
            data = urlencode(data)

        if log:
            log.debug('%s?%s - %s' % (getattr(settings, page), data or '', headers))

        params = { 
          'headers': headers
        }

        if data and force_get:
            params['url'] = getattr(settings, page) + '?' + data
        elif page in ('DOWNLOAD','XML_SEARCH'):
            params['url'] = getattr(settings, page) + data
        else:
            params['data'] = data
        #elif data:
        #    headers.update({'Content-type': 'application/x-www-form-urlencoded;charset=utf-8'})

        params['url'] = getattr(settings, page)

        response = self.opener.open(**params)
        log.debug(response.headers)

        return response

    def __validate_special_page(self, page, data={}, **kwargs):
        """
        Validates a given special page for an 'ok' response
        """
        data.update(kwargs)
        load_and_validate(self.__do_special_page(page, data))

    _Phone__validate_special_page = __validate_special_page
    
    def __do_special_page(self, page, data=None, headers={}, force_get=False):
        """
        Add self.special to request data
        """
        assert self.special, 'You must login before using this page'
        if isinstance(data, tuple):
            data += ('_rnr_se', self.special)
        elif isinstance(data, dict):
            data.update({'_rnr_se': self.special})
        return self.__do_page(page, data, headers, force_get)
        
    _Phone__do_special_page = __do_special_page
    
    def __get_xml_page(self, page, data=None, headers={}):
        """
        Return XMLParser instance generated from given page
        """
        return XMLParser(self, page, lambda: self.__do_page('XML_%s' % page.upper(), data, headers, True).content)
      
    def __messages_post(self, page, *msgs, **kwargs):
        """
        Performs message operations, eg deleting,staring,moving
        """
        data = kwargs.items()
        for msg in msgs:
            if isinstance(msg, Message):
                msg = msg.id
            assert is_sha1(msg), 'Message id not a SHA1 hash'
            data += (('messages',msg),)
        return self.__do_special_page(page, dict(data))
    
    _Message__messages_post = __messages_post
