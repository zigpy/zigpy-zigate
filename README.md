# zigpy-zigate fork for Zigbee for Domoticz plugin

We have done this fork deliberatly because it was out-dated, not really maintained and in order for us to achieve our object developp our plugion for domoticz  relying on zigpy-<radio> libraries. 

Our intent is not to use the zigpy-zigate library other than during our developpement and test phase as the all plugin has been developped for Zigate in native mode.

This library was very out-dated, based on old zigate firmware, not able to handle the Zigate protocol, which was creating a lot transmission errors on the firmware side.
Group and broadcast requests were also missing

However , all changes we have done have been done in a way that the zigpy-zigate library behave as the other zigpy-<radio> libraries, our intent was never to do something specific in any means.
