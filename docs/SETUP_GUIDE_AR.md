# دليل الإعداد: من الصفر إلى أول PR مدموج

هذا الدليل لك أنت (المشغّل). ينقلك من التطبيق الموجود على هذا الخادم إلى خط بناء يعمل وحده في
Claude Console حتى يكتمل المنتج. التسميات الإنجليزية والأوامر مكتوبة كما تظهر تماماً.

**كيف يعمل الخط باختصار:** وكيلان في Claude Console يعملان بجدولة كل نصف ساعة. «الباني»
(`ac-builder`) ينفّذ مهمة واحدة ويفتح PR. GitHub يشغّل الاختبارات (CI). «المراجع» (`ac-reviewer`)
يراجع، وإن وافق دمج. GitHub نفسه يمنع الدمج ما لم ينجح CI ويوافق المراجع. التفاصيل في
`pipeline/README.md`.

**الوقت المتوقع للإعداد:** 60 إلى 90 دقيقة.

---

## 0. قبل أن تبدأ

- حساب GitHub، وحساب Claude Console فيه رصيد.
- طرفية على هذا الخادم بالمستخدم `frappe`.
- **التوقيت:** إن كان جزء من رصيدك ينتهي قريباً فابدأ اليوم؛ كل تأخير يضيّع منه.

كل الأوامر التالية من مجلد التطبيق ما لم يُذكر غير ذلك:

```bash
cd /home/frappe/frappe-bench/apps/attention_center
```

---

## 1. GitHub: المستودع

### 1.1 أنشئ المستودع

1. في GitHub اضغط **New repository**.
2. **Repository name:** `attention_center`. **Visibility:** `Public`.
3. لا تضف README ولا .gitignore ولا license (المستودع يجب أن يكون فارغاً).
4. اضغط **Create repository**.

### 1.2 قيّد التفاعل بالمتعاونين فقط

**Settings → Moderation → Interaction limits → Limit to repository collaborators → Enable** (اختر أطول مدة).

> **لماذا؟** المستودع عام، وأي شخص يستطيع فتح Issue أو تعليق. الوكلاء يقرأون التعليقات، فنمنع الغرباء من الكتابة أصلاً. والسكربت يتجاهل أيضاً كل ما لم يكتبه مالك المستودع.

### 1.3 أنشئ ثلاثة توكنات

**Settings (حسابك) → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token.**
لكل توكن: **Repository access → Only select repositories →** `attention_center`، ثم **Repository permissions** كما في الجدول. انسخ كل توكن فور إنشائه.

| التوكن (Token name) | Contents | Pull requests | Actions | Issues | Commit statuses | Workflows | Expiration |
|---|---|---|---|---|---|---|---|
| `ac-setup` (مؤقت) | Read and write | — | — | — | — | Read and write | 7 days |
| `ac-builder` | Read and write | Read and write | Read-only | Read and write | Read-only | — | 2026-12-15 |
| `ac-reviewer` | Read and write | Read and write | Read-only | Read and write | Read and write | — | 2026-12-15 |

> **لماذا ثلاثة؟** أقل صلاحية لكل دور، وعلى هذا المستودع وحده.
> - `ac-builder` لا يملك **Commit statuses: write**، فلا يستطيع أن يمنح نفسه موافقة المراجعة.
> - لا أحد من الوكيلين يملك **Workflows**، فلا يستطيعان تعديل ملف CI.
> - `ac-setup` للرفع الأول فقط (لأن رفع ملف CI يتطلب Workflows)، وتحذفه بعده.

### 1.4 ارفع التطبيق

```bash
git remote add origin https://github.com/<USER>/attention_center.git
git -c credential.helper= push -u origin main
```

عند السؤال: **Username** = اسم مستخدمك في GitHub، **Password** = توكن `ac-setup`.
بعد نجاح الرفع احذف توكن `ac-setup` من صفحة التوكنات.

> الـ commit المحلي باسم محايد (`Attention Center Contributors`). إن أردت أن يظهر باسمك في GitHub فغيّر الهوية قبل الرفع:
> `git config user.name "<name>" && git config user.email "<GitHub noreply email>" && git commit --amend --reset-author --no-edit`

### 1.5 انتظر أول تشغيل لـ CI

افتح تبويب **Actions** في المستودع. الرفع يشغّل workflow اسمه **CI** فيه job اسمه **tests** (نحو 10 دقائق).
إن فشل فلا بأس الآن: أول مهمة للباني (`M0-T1`) هي جعله أخضر.

### 1.6 أدخل التوكنين في الطرفية (لا يُحفظان في أي ملف)

```bash
read -s -p "builder token: " AC_BUILDER_REPO_TOKEN; export AC_BUILDER_REPO_TOKEN; echo
read -s -p "reviewer token: " AC_REVIEWER_REPO_TOKEN; export AC_REVIEWER_REPO_TOKEN; echo
export AC_REPO_URL="https://github.com/<USER>/attention_center"
```

تحقق من الوصول:

```bash
AC_GITHUB_TOKEN="$AC_REVIEWER_REPO_TOKEN" python3 scripts/pipeline/status.py doctor
```

يجب أن يطبع اسم المستودع و`"visibility": "public"`.

### 1.7 سجّل فحص المراجعة ليظهر في إعدادات الحماية

```bash
AC_GITHUB_TOKEN="$AC_REVIEWER_REPO_TOKEN" python3 scripts/pipeline/status.py seed-review-status
```

### 1.8 احمِ الفرع main

**Settings → Branches → Add classic branch protection rule:**

- **Branch name pattern:** `main`
- ✅ **Require a pull request before merging**، واجعل **Required approvals** = `0`
- ✅ **Require status checks to pass before merging**، ثم ابحث وأضف: `tests` و `agent-review`
- ✅ **Do not allow bypassing the above settings**
- اضغط **Create**.

ثم **Settings → General → Pull Requests:** أبقِ ✅ **Allow squash merging** فقط، وفعّل ✅ **Automatically delete head branches**.

> **لماذا؟** هذه هي البوابة الحقيقية: GitHub يرفض أي دمج إلى `main` قبل نجاح `tests` ووجود حالة `agent-review` ناجحة على الـ commit نفسه، ويرفض الدفع المباشر إلى `main` حتى منك. فلا يعتمد الأمان على التزام النموذج بالتعليمات.
> إن لم يظهر `tests` في البحث فانتظر انتهاء أول تشغيل لـ CI ثم أعد المحاولة.

---

## 2. Claude Console: مساحة العمل وسقف الإنفاق

1. افتح <https://platform.claude.com> ثم **Settings → Workspaces → Create workspace**، وسمِّها `attention-center`.
2. في إعدادات هذه الـ workspace اضبط **Spend limit** على مبلغ أقل قليلاً من رصيدك المتاح، ليبقى احتياطي.
3. افتح **Settings → Billing** وسجّل الرصيد المتبقي الآن (ستقارن به بعد أول جلسة).

> **لماذا workspace مستقلة؟** الوثائق تنص على أن الـ workspace الافتراضية لا تقبل سقف إنفاق. السقف هنا هو الحد الأعلى الإجمالي مهما حدث، وفوقه سقف لكل جلسة (10 دولارات للباني و3 للمراجع) مضبوط في الجدولة.
> أسماء القوائم في Console قد تختلف قليلاً عما هنا؛ لم أستطع رؤية الواجهة نفسها، فاعتمدت على الوثائق.

---

## 3. أداة `ant` وتسجيل الدخول

```bash
mkdir -p ~/.local/bin
VERSION=2.8.0
curl -fsSL "https://github.com/anthropics/anthropic-cli/releases/download/v${VERSION}/ant_${VERSION}_linux_amd64.tar.gz" | tar -xz -C ~/.local/bin ant
export PATH="$HOME/.local/bin:$PATH"
ant --version
ant auth login --no-browser
```

الأمر الأخير يطبع رابطاً: افتحه في متصفحك، اختر workspace `attention-center`، ثم الصق الرمز في الطرفية. تحقق:

```bash
ant auth status
```

> **لماذا `ant auth login` وليس API key؟** لا يوجد مفتاح ثابت تحفظه أو يتسرب؛ الدخول برمز قصير العمر مربوط بهذه الـ workspace.
> البديل إن فضّلت: أنشئ مفتاحاً من **API keys** داخل الـ workspace ثم `export ANTHROPIC_API_KEY=...` في الطرفية فقط، ولا تكتبه في أي ملف.

---

## 4. أنشئ الوكيلين والبيئة والخزنتين

```bash
ant apply --dry-run pipeline/agents pipeline/environments pipeline/vaults
ant apply pipeline/agents pipeline/environments pipeline/vaults
```

الأمر الأول يعرض الخطة فقط. الثاني يسأل `Apply these changes?` فأجب `y`. يُنشأ:
`ac-builder`، `ac-reviewer`، البيئة `ac-bench`، والخزنتان `ac-builder` و`ac-reviewer`.
ويُكتب الملف `claude-lock.json` في مجلد التطبيق: **لا تحذفه** (فيه معرّفات ما أُنشئ، وهو مستثنى من git).

ثم خزّن التوكنين في الخزنتين وأنشئ الجدولة:

```bash
pipeline/deployments.sh credentials
pipeline/deployments.sh create
pipeline/deployments.sh list
```

> **أين تُحفظ الأسرار؟** في مكانين داخل Console فقط: خزنة كل وكيل (لاستدعاء GitHub API)، ومورد المستودع في الجدولة (لـ `git push`). بحسب الوثائق لا تدخل قيمة التوكن إلى الحاوية؛ يُستبدل بها عند خروج الطلب إلى `api.github.com` فقط. لا يوجد أي سر في المستودع.
> **الشبكة:** البيئة `limited`، فلا تصل الحاوية إلا إلى مستودعات الحزم وGitHub. لا تصل إلى شبكتكم الداخلية ولا إلى هذا الخادم ولا إلى بياناتكم.

### اختيار نموذج الباني

الباني مضبوط على `claude-sonnet-5-5`، وهو الأنسب لتكلفة المشروع كله. إن أردت نموذجاً أقوى
لمراحل الأساس (M0 إلى M2)، مثلاً لأن لديك رصيداً سينتهي قريباً، فافتح `pipeline/agents/builder.md`
وغيّر `id: claude-sonnet-5-5` إلى `id: claude-opus-5-5` ثم:

```bash
ant apply pipeline/agents/builder.md
```

وأعده إلى `claude-sonnet-5-5` بالطريقة نفسها بعد المرحلة M2. إن كان لديك أكثر من رصيد، فراجع
**Settings → Billing** بعد أول جلسة لترى أيها يُستهلك أولاً (الوثائق لا تذكر الترتيب).

---

## 5. التشغيل والمراقبة

الجدولة تبدأ وحدها عند الدقيقة 05 و35 (الباني) و20 و50 (المراجع) من كل ساعة بتوقيت UTC. لتبدأ الآن:

```bash
pipeline/deployments.sh run builder
```

**المراقبة:** Console → **Managed Agents → Sessions**. لكل جلسة: النص الكامل، استدعاءات الأدوات، والتكلفة.

**ما تتوقعه في أول دورة:**

1. جلسة الباني تأخذ المهمة `M0-T1`، وتفتح PR عنوانه `WIP: [M0-T1] …`، وتبني bench داخل الحاوية (قد تستغرق 30 إلى 60 دقيقة لأنها أول مرة).
2. عند الانتهاء يصير العنوان `[M0-T1] …` ويعمل CI.
3. جلسة المراجع التالية تكتب مراجعتها كتعليق على الـPR. إن وافقت دمجت: **هذا أول PR مدموج.** وإن طلبت تعديلات عالجها الباني في جلسته التالية.
4. بعد الدمج يأخذ الباني المهمة التالية تلقائياً، وهكذا حتى `M7-T4`.

**التكلفة:** المهمة العادية بين دولارين وأربعة للباني ونحو دولار للمراجعة. الجلسات التي لا تجد عملاً تنتهي بعد أمر واحد وتكلّف سنتات. تقديري للمشروع كله 120 إلى 160 دولاراً؛ راقب صفحة Billing يومياً في الأيام الأولى.

### التحكم

| ماذا تريد | كيف |
|---|---|
| إيقاف مؤقت / استئناف | `pipeline/deployments.sh pause` ثم `unpause` |
| تشغيل جلسة الآن | `pipeline/deployments.sh run builder` أو `run reviewer` |
| إيقاف كل شيء لسؤال أو مراجعة | افتح Issue عنوانه يبدأ بـ `[pipeline-halt]`، وأغلقه للاستئناف |
| الإجابة عن سؤال طرحه وكيل | علّق على الـIssue الذي عنوانه `[needs-human]` (تُقرأ تعليقاتك أنت فقط) |
| السماح بمحاولات جديدة لـPR متعثر | علّق `/retry` على الـPR ثم أغلق Issue التوقف |
| معرفة الحالة | `AC_GITHUB_TOKEN="$AC_BUILDER_REPO_TOKEN" python3 scripts/pipeline/status.py state` |

بعد خمس محاولات فاشلة على PR واحد يتوقف الخط ويفتح لك Issue بعنوان `[pipeline-halt]` يشرح ما يحتاجه. GitHub يرسل لك بريداً بذلك.

**عند اكتمال كل المهام** تطبع الجلسات `DONE`. أوقف الجدولة حينها: `pipeline/deployments.sh pause`.

---

## 6. المراجعة والتجربة على هذا الخادم

اجلب آخر ما دُمج:

```bash
cd /home/frappe/frappe-bench/apps/attention_center && git pull
```

**اختبار على موقع نظيف** (يطلب كلمة مرور root لـ MariaDB):

```bash
cd /home/frappe/frappe-bench
bench new-site attention-test.local --admin-password '<password>'
bench --site attention-test.local install-app attention_center
bench --site attention-test.local set-config allow_tests true
bench --site attention-test.local run-tests --app attention_center
```

**معاينة الواجهة ببيانات الموقع التجريبي** (بعد دمج المرحلة M3):

```bash
bench --site site1.local install-app attention_center
bench --site site1.local migrate
bench build --app attention_center
sudo supervisorctl restart all
```

وإن شغّلت الاختبارات على `site1.local` فأضف `--skip-test-records --skip-before-tests`.

**الاستماع للنغمات الآن:** افتح في متصفحك عنوان موقعك متبوعاً بـ
`/assets/attention_center/sounds/preview.html`. إن لم تعجبك نغمة أخبرني لأعدّلها في
`scripts/sounds/generate_tones.py` قبل وصول الخط إلى مهمة الصوت (`M4-T2`).

**توافق الثيمات:** الوكلاء يختبرون على واجهة Frappe القياسية فقط لأنهم لا يملكون ثيماتكم. بعد M3 جرّب الواجهة هنا مع الثيم المستخدم عندكم، وافتح Issue بأي خلل.

---

## 7. ملخص قرارات الأمان

| القرار | السبب |
|---|---|
| توكن مستقل لكل وكيل، على مستودع واحد، بأقل صلاحيات | حصر الضرر إن أخطأ وكيل، ومنع الباني من اعتماد عمله |
| لا صلاحية Workflows للوكلاء | لا يستطيعون تعطيل الاختبارات |
| حماية `main` بفحصين إلزاميين ومنع التجاوز | بوابة يفرضها GitHub لا التعليمات |
| الأسرار في خزنة Console ومورد الجدولة فقط | لا سر في المستودع ولا داخل الحاوية |
| شبكة `limited` للحاوية | لا وصول لشبكتكم ولا لبياناتكم |
| تقييد التفاعل وتجاهل كتابات غير المالك | المستودع عام، ونصوص الغرباء قد تحمل تعليمات مدسوسة |
| سقف لكل جلسة وسقف للـworkspace | لا مفاجآت في الإنفاق |
| تسجيل الدخول بـ`ant auth login` | لا مفتاح API ثابت يُحفظ |

---

## 8. إن حدث خلل

| العَرَض | الحل |
|---|---|
| `ant apply` يرفض البيئة أو جلسة لا تبدأ بسبب الحزم | احذف قسم `packages` من `pipeline/environments/bench.yaml`، ثم `ant apply pipeline/environments/bench.yaml`. سكربت `scripts/dev/bench_up.sh` يحاول التثبيت داخل الجلسة |
| جلسة الباني تقول إن `AC_GITHUB_TOKEN` غير موجود أو يُرفض | أعد `pipeline/deployments.sh credentials` بعد التأكد من التوكنين، وتأكد أن `api.github.com` مسموح في بيانات الاعتماد |
| الدمج يُرفض برسالة عن status check | تأكد أن الاسمين في حماية الفرع هما `tests` و`agent-review` بالضبط |
| لا يظهر `tests` عند إضافة الفحوص | انتظر اكتمال أول CI على `main` |
| جلسات كثيرة تنتهي بـ`WAIT` | طبيعي أثناء عمل CI أو جلسة أخرى |
| انتهى الرصيد | تتوقف الجلسات. كل ما دُمج محفوظ في GitHub، والخط يُكمل من حيث توقف متى توفر رصيد |

---

## 9. ما تحققتُ منه وما لم أتحقق

تحققتُ من الوثائق الرسمية بتاريخ 2026-11-09:

- `git push` من الجلسة بتوكن المستودع، وحقول `github_repository`: <https://platform.claude.com/docs/en/managed-agents/github>
- البيئة: `packages` (ومنها `apt`)، شبكة `limited`، وقائمة مستودعات الحزم المسموحة: <https://platform.claude.com/docs/en/managed-agents/environments>
- مواصفات الحاوية (Ubuntu 24.04، حتى 8 GB ذاكرة و10 GB قرص، Redis وPostgreSQL مثبتان، لا ذكر لـ MariaDB): <https://platform.claude.com/docs/en/managed-agents/cloud-sandboxes-reference>
- الجدولة، وسقف كل تشغيل، والتشغيل اليدوي، والإيقاف المؤقت: <https://platform.claude.com/docs/en/managed-agents/scheduled-deployments>
- الخزنة وبيانات الاعتماد من نوع `environment_variable`: <https://platform.claude.com/docs/en/managed-agents/vaults>
- `ant apply` وتثبيت `ant`: <https://platform.claude.com/docs/en/cli-sdks-libraries/cli/apply> و <https://platform.claude.com/docs/en/cli-sdks-libraries/cli/quickstart>
- صلاحيات توكنات GitHub لكل endpoint: <https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens>

**لم يُختبر عملياً بعد** (لا أملك حسابك، وأول تشغيل هو الاختبار):

- تثبيت MariaDB وتشغيله داخل الحاوية. إن تعذّر فالمهمة `M0-T1` تنتقل إلى PostgreSQL محلياً وتبقي MariaDB في CI.
- ملف CI وسكربت `bench_up.sh`: مبنيان على قالب Frappe الرسمي لكن لم يعملا على GitHub بعد.
- سكربت `pipeline/deployments.sh`: صيغة أوامر `ant` مأخوذة من الوثائق، ولم تُنفَّذ.
- ماذا يحدث لو بدأ تشغيل مجدول وجلسة سابقة ما زالت تعمل: الوثائق لا تذكره، فصمّمتُ السكربت ليتحمّل التداخل (حجز الـPR بعنوان `WIP:`).
- ترتيب استهلاك الأرصدة إن تعددت، وهل تغطي الأرصدة الترويجية تكلفة زمن الجلسة: غير مذكور صراحةً في الوثائق.
