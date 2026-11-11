<h2>1. Who is responsible</h2>
<p>PocketBrain is operated by <strong><?= legalEscape($operator['name'] ?: '[Operator name to be completed]') ?></strong>,
which is responsible for personal data processed to run this service.
Contact: <?php if ($operator['email'] !== ''): ?><a href="mailto:<?= legalEscape($operator['email']) ?>"><?= legalEscape($operator['email']) ?></a><?php else: ?>[Privacy contact email to be completed]<?php endif; ?>.</p>
<?php if ($operator['address'] !== ''): ?><p>Address: <?= legalEscape($operator['address']) ?>.</p><?php endif; ?>

<h2>2. What we process and why</h2>
<ul>
<li><strong>Accounts:</strong> email address, password hash, role, account status, invitation records, and signup time, to provide access and manage accounts. Passwords are stored as hashes, not as readable passwords.</li>
<li><strong>Devices:</strong> device identifiers and names, pairing records, credential hashes, linked/unlinked status, last-seen times, and active conversation selections, to connect your devices to your account.</li>
<li><strong>Conversations:</strong> question and reply text, source links, thread titles, language metadata, timestamps, and device attribution, to save and resume conversations across your devices.</li>
<li><strong>Voice:</strong> microphone recordings are buffered on the device or desktop app and sent directly to OpenAI for transcription and voice responses. The current PHP backend stores transcripts, not audio recordings. A pending recording and local transcript cache may remain on your device until saved, discarded, or cleared.</li>
<li><strong>API keys:</strong> if you add an OpenAI key, the backend stores an encrypted copy and decrypts it to request voice credentials or web searches. Your devices receive short-lived voice credentials rather than your long-lived key.</li>
<li><strong>Lookups:</strong> web-search queries are sent to OpenAI. Weather location queries and resolved coordinates are sent to Open-Meteo. The app does not automatically determine your location from GPS.</li>
<li><strong>Security and preferences:</strong> IP-derived rate-limit identifiers, authentication/session information, cookie choices, and document-version acceptance records help protect the service and remember your preferences. Hosting providers may additionally process access/error logs and IP addresses.</li>
</ul>

<h2>3. Proposed purposes and legal bases</h2>
<p>Account access, device linking, requested AI operations, and saved history are intended to be processed as necessary to provide the service you request. Security and abuse prevention are intended to rely on legitimate interests where appropriate; applicable legal obligations may require other processing. These proposed bases must be reviewed by the operator for its actual service and users before publication.</p>
<p>Acknowledging this policy is not blanket consent to all processing. Optional cookies or any future optional uses requiring consent need a separate choice. There are currently no optional analytics or advertising cookies.</p>

<h2>4. Who receives data</h2>
<p>The hosting/database provider processes data needed to operate the site. The current deployment uses Loopia. OpenAI receives the audio, conversation context, and queries needed for AI requests. Open-Meteo receives weather queries; its geocoding uses GeoNames location data. Information included in web-search queries may be disclosed to search services involved in fulfilling them. Do not put secrets or unnecessary personal details into a lookup.</p>
<p>Provider processing, retention, and international transfers depend on their current terms, account settings, and the operator's agreements. The operator must confirm applicable providers, processing locations, transfer safeguards, and any subprocessors before publishing this policy. This draft does not claim that all data stays in Sweden or the EEA, or that providers keep no request data.</p>

<h2>5. Retention and deletion</h2>
<p>Conversations remain in the live backend until you delete them. Devices may retain cached or pending copies until they next synchronize or you clear local data. Deletion is not a promise of immediate secure erasure from device flash, backups, or a provider's systems.</p>
<p>Account/device records and encrypted keys are retained while needed to operate your account. You can remove your saved API key in the dashboard; separately revoke it at OpenAI when appropriate. Account deletion/export requests can be made through the contact above; there is no automatic account-deletion page at present.</p>
<p>The application documents daily cleanup of old rate-limit entries and expired pairing records. The operator must confirm that these jobs run and specify actual account, log, backup, and legal-record retention periods before publishing. No fixed backup or hosting-log deletion period has been verified for this draft.</p>

<h2>6. Cookies</h2>
<p>The PocketBrain session cookie supports sign-in and form protection. A separate preference cookie remembers your optional-cookie choice for 180 days. Both are marked Secure, HttpOnly, and SameSite=Lax. Essential cookies remain active whether you accept or reject optional cookies. Change the optional-cookie choice through <a href="index.php?cookie-settings=1#cookie-banner">Cookie preferences</a>. No optional tracking services are currently loaded.</p>

<h2>7. Security and your choices</h2>
<p>We use access checks, encrypted transport, hashed passwords and device credentials, and encrypted backend API-key storage. These measures do not guarantee complete security. Cached device data and desktop recordings require protection on your own hardware. Protect your sign-in details, revoke lost devices, and clear local data before transferring a device.</p>
<p>Depending on applicable law, you may request access, correction, deletion, restriction, or portability of your data, and object to certain processing. If a particular use relies on consent, you may withdraw that consent without changing the lawfulness of earlier processing. Contact the operator to exercise your rights. You may also complain to your local data-protection authority; in Sweden this is <a href="https://www.imy.se/en/individuals/">IMY</a>.</p>

<h2>8. Children, changes, and contact</h2>
<p>Do not submit another person's personal data without a lawful basis, or record others without the rights and permissions required in your situation. The operator must review age eligibility and any safeguards required for children before offering the service to them.</p>
<p>We will publish dated versions when this policy changes. A material new purpose for processing requires appropriate information and any additional choice required by law. Questions or requests should go to the operator identified above.</p>
