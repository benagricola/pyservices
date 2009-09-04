#!/usr/bin/env python

import tools

str = "2009-09-02 21:14:27,757 ST_RECEIVER VERBOSE Peer Modules: ['m_banexception.so', 'm_banredirect.so', 'm_blockcolor.so', 'm_botmode.so', 'm_cban.so', 'm_chanfilter.so', 'm_channelban.so', 'm_chanprotect.so', 'm_chghost.so', 'm_chgname.so', 'm_delayjoin.so', 'm_globalload.so', 'm_globops.so', 'm_hidechans.so', 'm_hideoper.so', 'm_invisible.so', 'm_joinflood.so', 'm_messageflood.so', 'm_nickflood.so', 'm_nicklock.so', 'm_nonicks.so', 'm_operchans.so', 'm_operinvex.so', 'm_permchannels.so', 'm_redirect.so', 'm_regex_glob.so', 'm_sajoin.so', 'm_sakick.so', 'm_sanick.so', 'm_sapart.so', 'm_saquit.so', 'm_services_account.so', 'm_setident.so', 'm_shun.so', 'm_sslmodes.so', 'm_stripcolor.so', 'm_svshold.so', 'm_swhois.so', 'm_timedbans.so', 'm_watch.so']"

print tools.word_wrap(str, width=140, offset=49)