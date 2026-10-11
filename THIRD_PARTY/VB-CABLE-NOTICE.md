# VB-CABLE virtual audio driver

Clear Mic includes the complete, unmodified VB-CABLE Driver Pack 45 by **VB-Audio Software / Vincent Burel**. The binary driver is proprietary and retains its vendor license; it is not covered by Clear Mic's MIT license.

VB-CABLE is **donationware**. Contributions to its developer are welcome:

- Origin, product information and donation links: https://vb-audio.com/Cable/
- Distribution permission and licensing terms: https://vb-audio.com/Services/licensing.htm
- The vendor's end-user agreement is retained as `readme.txt` inside the bundled package.

The current distribution terms explicitly allow bundling VB-CABLE with an application when its origin, identity and donationware model remain visible. Clear Mic keeps these notices visible in the setup screen and Settings, keeps the full original package, and uses device names that identify VB-Audio.

Clear Mic's setup creates a dedicated Plug-and-Play instance with the unmodified signed driver. It refuses to create another instance when a separate VB-CABLE installation is present, and its removal helper targets only `ROOT\CLEARMIC\0000`.
