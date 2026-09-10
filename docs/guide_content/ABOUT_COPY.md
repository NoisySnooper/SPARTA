ABOUT WINDOW COPY

<!-- R2 handoff for the structural writer (PLAN_v149 Phase R2 item
     1). This is the slimmed About window body, to be wired verbatim
     minus these comments. It is NOT a guide view: do not add it to
     manifest.json's views or to the View dropdown, and exclude it
     from the honesty gate.
     {VERSION} is APP_VERSION at build time. The wordmark, expansion
     and org lines are built from BRAND exactly as the header does
     today (lowercase wordmark + ac2 dot, rule 43); they are shown
     here only so the copy reads whole. The GitHub, Welcome & tour
     and Close buttons stay on the button bar. Everything About used
     to teach now lives in the tour and the guide views.
     R4 item 9 (Nhan): the author line reads "Nhan Ta"; the
     "vendored under the MIT license by his permission" line is gone;
     Matthew's own repository is a second link line under his credit,
     formatted like the SPARTA one. Both URL lines are rendered as
     live links in the window. -->

sparta.  {VERSION}
SPectroscopic Absorption, Real Time Analysis
formerly SQUISHE / the Beamline DAC Data Tool

SPARTA turns a beamtime's folders of raw segment files into
absorbance. It draws publication figures. It reads sample
thickness from the fringes.

Written by Nhan Ta, Dr. Lee's Lab, NSLS-II 22-IR-1.
The fringe-analysis core is Matthew R. Diamond's defringe_dac.py:
https://github.com/matthewrdiamond/DAC-Absorption-Fringe-Analysis

MIT licensed. Source, issues and releases:
https://github.com/NoisySnooper/SPARTA

'Welcome & tour...' starts the tour.
