<h2>1. The service and agreement</h2>
<p>These terms govern your use of PocketBrain, operated by <strong><?= legalEscape($operator['name'] ?: '[Operator name to be completed]') ?></strong>.
Contact: <?php if ($operator['email'] !== ''): ?><a href="mailto:<?= legalEscape($operator['email']) ?>"><?= legalEscape($operator['email']) ?></a><?php else: ?>[Operator contact email to be completed]<?php endif; ?>.</p>
<p>PocketBrain is an experimental, invitation-based voice assistant with linked devices and saved conversation history. You agree to these terms when creating an account. You must have the legal capacity and permissions needed to use the service and comply with applicable third-party eligibility requirements.</p>

<h2>2. Your account and devices</h2>
<p>Provide accurate account information and protect your password and device credentials. Use only invitations and accounts you are authorized to use. Your linked devices share your account's conversations. Revoke lost devices through the dashboard and clear their local data before transfer. Tell the operator if you suspect unauthorized use.</p>

<h2>3. Acceptable use and recordings</h2>
<p>Use PocketBrain lawfully. Do not attempt unauthorized access, steal credentials, interfere with other users, distribute unlawful content, bypass limits, or deliberately overload the service. Submit only content and recordings you have the right to use, including any permissions needed when recording other people. Avoid unnecessary sensitive information and secrets in conversations or searches.</p>

<h2>4. AI output and current information</h2>
<p>AI replies can be inaccurate, incomplete, biased, or out of date. Search results and weather forecasts can also be wrong or unavailable. Check important information against reliable sources. PocketBrain is not an emergency service and is not a substitute for qualified medical, legal, financial, or other professional advice. You are responsible for deciding whether an answer is suitable for your situation.</p>

<h2>5. API keys, providers, and charges</h2>
<p>If you supply an OpenAI API key, you authorize PocketBrain to use it on the server to provide the AI features you request. Use a dedicated key you are entitled to use, check your API account permissions and usage, and revoke the key when it is no longer needed. API use can create charges under your agreement with OpenAI. Short-lived voice credentials and open sessions may remain usable for their provider-defined lifetimes after removing a key or unlinking a device.</p>
<p>The app's request/recording limits are not a guaranteed spending cap. If the operator explicitly enables shared billing, users without personal keys may use the operator's API account as described in the dashboard. These terms do not create a paid PocketBrain subscription; any separate service charges must be disclosed and agreed before purchase. Third-party services have their own applicable terms.</p>

<h2>6. Your content and privacy</h2>
<p>You retain any rights you have in content you submit. You allow the operator and its necessary providers to process that content to deliver, secure, and maintain the features you request, subject to applicable law and the privacy policy. These terms do not give permission to sell your conversations or use them for unrelated advertising. AI output may not be unique and may involve third-party rights.</p>
<p>Read the <a href="<?= legalEscape(legalUrl('privacy')) ?>">privacy policy</a> for data handling and requests. Acknowledging that policy is separate from optional-cookie consent. Keep your own copies of information you need; local caches and backups may not disappear immediately when you delete a conversation.</p>

<h2>7. Availability, suspension, and ending use</h2>
<p>Features may change, be interrupted, or stop working, especially during prototype development. We do not promise uninterrupted availability or error-free output. The operator may restrict or suspend access where reasonably needed to prevent abuse, address security issues, comply with law, or respond to a material breach of these terms.</p>
<p>You may stop using the service and request account deletion using the contact above. Stopping use does not automatically revoke API keys or cancel charges already incurred with third-party providers. Any notice, cancellation, refund, or other rights required by applicable law continue to apply.</p>

<h2>8. Responsibility and your legal rights</h2>
<p>Use the service with care and take reasonable steps to protect your data and account. Responsibility for loss depends on the circumstances and applicable law. Nothing in these terms excludes or limits liability, consumer rights, or data-protection rights that cannot lawfully be excluded or limited.</p>

<h2>9. Changes and disputes</h2>
<p>Revised terms will be identified by a new version and made available before they take effect. Material changes should be notified and any agreement required by law obtained; acceptance of this version is not automatic acceptance of every future version. Contact the operator first about questions or disputes. Applicable mandatory law and any rights to complain to competent authorities or bring proceedings in a competent court are preserved.</p>
