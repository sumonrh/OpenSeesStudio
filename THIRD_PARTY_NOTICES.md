# Third-Party Notices

OpenSees Studio is source-available under the **PolyForm Noncommercial License
1.0.0**. See `LICENSE.txt` and `NOTICE.md`. This file is included with the
application, portable build, and installer.

OpenSees Studio does not grant any rights to the third-party components below
beyond those granted by their own licensors. The complete license texts are in
the `licenses/` folder.

## OpenSees and OpenSeesPy

OpenSees Studio imports OpenSeesPy (`openseespy.opensees`) and distributes the
compiled `openseespywin/opensees.pyd` engine. OpenSees and OpenSeesPy remain
copyrighted by The Regents of the University of California and are not covered
by the PolyForm Noncommercial license.

### OpenSees copyright and license

```text
Copyright @ 1999-2020 The Regents of the University of California (The Regents). All Rights Reserved.

The Regents grants permission, without fee and without a written license agreement, for (a) use,
reproduction, modification, and distribution of this software and its documentation by educational,
research, and non-profit entities for noncommercial purposes only; and (b) use, reproduction and
modification of this software by other entities for internal purposes only. The above copyright
notice, this paragraph and the following three paragraphs must appear in all copies and modifications
of the software and/or documentation.


Permission to incorporate this software into products for commercial distribution may be obtained
by contacting the University of California
Office of Technology Licensing
2150 Shattuck Avenue #510,
Berkeley, CA 94720-1620,
(510) 643-7201.

This software program and documentation are copyrighted by The Regents of the University of California.
The Regents does not warrant that the operation of the program will be uninterrupted or error-free. The
end-user understands that the program was developed for research purposes and is advised not to rely
exclusively on the program for any reason.

IN NO EVENT SHALL REGENTS BE LIABLE TO ANY PARTY FOR DIRECT, INDIRECT, SPECIAL, INCIDENTAL, OR CONSEQUENTIAL
DAMAGES, INCLUDING LOST PROFITS, ARISING OUT OF THE USE OF THIS SOFTWARE AND ITS DOCUMENTATION, EVEN IF REGENTS
HAS BEEN ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.  REGENTS GRANTS NO EXPRESS OR IMPLIED LICENSE IN ANY PATENT
RIGHTS OF REGENTS BUT HAS IMPLEMENTED AN INDIVIDUAL CONTRIBUTOR LICENSE AGREEMENT FOR THE OPENSEES PROJECT AT
THE UNIVERISTY OF CALIFORNIA, BERKELEY TO BENEFIT THE END USER.

REGENTS SPECIFICALLY DISCLAIMS ANY WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY
AND FITNESS FOR A PARTICULAR PURPOSE. THE SOFTWARE AND ACCOMPANYING DOCUMENTATION, IF ANY, PROVIDED HEREUNDER IS PROVIDED
"AS IS". REGENTS HAS NO OBLIGATION TO PROVIDE MAINTENANCE, SUPPORT, UPDATES, ENHANCEMENTS, OR MODIFICATIONS.
```

The complete OpenSees notice is also in `licenses/OpenSees-COPYRIGHT.txt`. The
OpenSees documentation at
<https://opensees.github.io/OpenSeesDocumentation/developer/license.html> also
reproduces BSD-3-Clause language; OpenSees Studio does not rely on that language
to permit commercial distribution. OpenSees documents that commercial
distribution requires a license from UC Berkeley.

### OpenSeesPy license

```text
OpenSeesPy is free for research, education, and internal use. Commercial redistribution
of OpenSeesPy, such as, but not limited to, an application or cloud-based service that
uses import openseespy, requires a license similar to that required for commercial
redistribution of OpenSees.exe. Contact Dr. Minjie Zhu (zhum@oregonstate.edu) for
commercial licensing details.
```

The complete OpenSeesPy notice is also in
`licenses/OpenSeesPy-LICENSE.md`.

## Qt and PySide6

OpenSees Studio uses PySide6 6.12.0 and Qt 6.12.0 under the **GNU Lesser
General Public License, version 3 (LGPL-3.0-only)**. The Qt libraries are
loaded dynamically from the application's `_internal/PySide6` folder and may be
replaced with compatible versions of the same libraries.

- Complete LGPL-3.0 text: `licenses/LGPL-3.0.txt`
- Complete GPL-3.0 text (incorporated by reference by LGPL-3.0):
  `licenses/GPL-3.0.txt`
- Qt/PySide6 source code and releases:
  <https://download.qt.io/official_releases/QtForPython/> and
  <https://code.qt.io/cgit/qt/>
- Qt third-party attributions:
  <https://doc.qt.io/qt-6/licenses-used-in-qt.html>
- Qt licensing information: <https://doc.qt.io/qt-6/licensing.html>

The GPL-only **Qt Virtual Keyboard** module and its plugin are not included in
the OpenSees Studio build. If you rebuild the application, do not add
GPL-only Qt modules unless the resulting distribution complies with their
licenses.

## Other runtime components

| Component | Version | License |
|---|---|---|
| Python | 3.12 | Python Software Foundation License 2.0 |
| NumPy | 2.5.4 | BSD-3-Clause and other permissive licenses (`licenses/NumPy-LICENSE.txt`) |
| MCP Python SDK | 2.3.0 | MIT |
| uvicorn / Starlette / HTTPX | current bundled versions | BSD-3-Clause |
| PyInstaller bootloader | 6.22.3 | GPL-2.0-or-later with the PyInstaller exception permitting distribution of non-free programs |

Other transitive dependencies retain their own licenses and are listed in the
installed package metadata. Their license texts are either included there or
available from the respective upstream projects.

## Questions

For OpenSees or OpenSeesPy commercial licensing, contact UC Berkeley's Office
of Technology Licensing and the OpenSeesPy maintainer. For OpenSees Studio
licensing questions, contact the OpenSees Studio contributors.
