# Parent-child linking: supplied archive evidence

Research date: 2026-10-28. This is local source research for the setup-help
quality gap in [family42](mana-parent-setup-support.md). It is not a current MANA
installation guide, a deployed feature, successful device pairing, or model-quality
acceptance. No model, network, cloud, Telegram, app or production operation was
performed. Only this document was authored.

## Provenance and applicability

The supplied file is `/mnt/ssd2/Downloads/bosstracker_parent-develop.zip`,
28,580,981 bytes, SHA-256
`5794cfce882876aaee57e163a793ec7b4d864e6c27d9fcde5eb23a9c64114036`.
Paths below are relative to its `bosstracker_parent-develop/` prefix. The inspected
entries have ZIP timestamps `2026-07-04 15:02:28`; ZIP timestamps have no timezone
and do not prove a release/deployment date. The ZIP comment is
`5e0ce8c6dcad1ff6e1aaa13fc2095254bac7edc1`, a revision-shaped provenance hint, not
an independently verified Git revision. No `.git` history is included.

The archive identifies itself as `boss_tracker_parent`, version **1.1.53+202**
(`pubspec.yaml:1–6`). The README calls it Boss Tracker Parent, lists Flutter
3.32.5 / Dart 3.8.1 and describes historical flavor entry points. Its active
Android namespace/application ID is `uz.bosstracker.khayot`
(`android/app/build.gradle.kts:12,33`); the manifest label is Glazok
(`android/app/src/main/AndroidManifest.xml:51`). iOS display/name is Glazok;
application build settings use `uz.bosstracker.glazok`, marketing version 1.1.53
and the Flutter build number (`ios/Runner/Info.plist`,
`ios/Runner.xcodeproj/project.pbxproj:534–546`, repeated release configurations).

The inspected API configuration uses host **api.g-lazok.uz**
(`lib/common/constants.dart:5,9,15`); both API base constants have an empty path.
The new child data source uses that configured base through `DioService`.
The relevant README/configuration contains no explicit MANA or api.manakids.uz
mapping. The archive's Glazok/Glazok 2 instructions therefore cannot be renamed
to MANA or treated as instructions for a parent's installed application merely
because the code was supplied for this project. The current parent/child release,
flavor, package pair and backend compatibility remain unverified.

## Actual parent-side route and API trace

The empty `lib/screens/connect_child/connect_child.dart` is a placeholder, not
the implemented flow. The relevant authenticated application path is:

1. `lib/bosstracker_app.dart:195–202` selects `MainPage` for an authenticated
   session without its PIN gate. `MainPage` embeds `HomePage`
   (`.../presentation/screens/main_page.dart:41–47`). Home fetches children with
   `GetChildrenEvent` and has an `add_child` button that pushes `AddChildScreen`
   (`.../presentation/screens/home_page.dart:73–88,135–138,211–225`). If the fetched list is
   empty, `WChildrenWidget` replaces the route with `InitialChildScreen`; its
   `add_child` button also opens `AddChildScreen`
   (`.../presentation/widgets/w_children_widget.dart:102–108`,
   `.../presentation/screens/initial_child_screen.dart:115–121`).
2. `AddChildScreen` uses a non-swipeable PageView: name, photo selection,
   photo/placeholder review, invitation-code widget
   (`.../presentation/screens/add_child_screen.dart:129–203`). The gender page is commented
   out; creation supplies `gender='male'` (`235–245`). Do not invent a visible
   gender, birth-date or phone-number step from the parameter model.
3. The name widget filters digits and advances only when the text length is
   greater than two (`.../presentation/widgets/child_name_screen.dart:65–91`). Photo selection
   offers camera/gallery; its close icon advances without a photo
   (`.../presentation/widgets/add_child_image.dart:78–108`, `add_child_screen.dart:165–187`).
   The review page's `ready` button invokes creation even with a null photo
   (`.../presentation/widgets/uploaded_image.dart:45–59,98–112`).
4. Creation submits `CreateChildEvent(AddChildParams(...))`. The active
   `ChildBloc` calls `ChildRepository.addChild` directly, not an
   `AddChildUseCase` instance (`.../presentation/bloc/child_bloc.dart:32–45`). The imported
   use-case file defines the parameters and a wrapper; its map contains
   `fullname`, `gender`, optional multipart `avatar`
   (`.../domain/use_case/add_child_use_case.dart:13–20,29–55`).
5. `ChildRepoImpl.addChild` delegates to `ChildRemoteDataSourceImpl.addChild`,
   which POSTs multipart form data to **`/api/v1/child/token/`** and extracts
   `response.data['token']` (`.../data/Repository/repository_implementation.dart:20–21`,
   `.../data/Data/remote/child_data_source.dart:30–38`,
   `lib/src/constants/request_path.dart:11–14`). This is a mobile write path,
   not an agent tool or authorization to call that API.
6. `CreateChildSuccessState` saves the returned token into `_invitationCode` and
   advances to `ChildInvitationCodeWidget`. A first-time local countdown overlay
   may appear first (`add_child_screen.dart:107–121,202`). It is not a separate
   pairing approval. Errors show `ErrorAlertDialog` (`122–126`).
7. The code widget displays the returned code and the localized instructions
   below. It listens for foreground FCM `type='childAdded'` and navigates to
   `MainPage(showReviewDialog:true)`; its home icon can navigate there manually
   (`.../presentation/widgets/child_code_widget.dart:23–45,50–56,192–208,359–380,413–416`).
   Manual navigation and a code being displayed do not prove a successful link.

Here `...` in paths means
`lib/src/features/child/`. These are source line references in the hashed archive,
not HTTP route names; this flow uses `MaterialPageRoute`, not the empty/commented
named-router files.

## Bounded instructions this snapshot supports

For this archived version only: open **Add child** in the parent app, enter the
name, optionally select a photo or skip it with the photo panel's close icon,
and press **Ready** on the review page. The parent app then displays an invitation
code. Its own instructions say to install/open **Glazok 2 on the child's Android
phone**, enter that displayed code **in the child app**, and grant the permissions
requested there. The archive does not establish the exact child-side screens,
button names, permission sequence or completion message.

The source localization loader registers `en-US`, `ru-RU`, `uz-UZ`, `uk-UA` from
`assets/langs` (`lib/main.dart:77–87`). The inspected Uzbek source is Latin script;
this evidence does not supply a reviewed Uzbek Cyrillic guide.

| Key | Russian label | Uzbek Latin label | English label |
| --- | --- | --- | --- |
| `add_child` | Добавить ребенка | Bolani qo'shish | Add child |
| `next` | Далее | Keyingisi | Next |
| `photo` | Фото | Rasm | Photo |
| `ready` | Готово | Tayyor | Ready |

Those exact labels are in `assets/langs/ru-RU.json:17,134,177,306`,
`uz-UZ.json:17,133,176,304` and `en-US.json:17,134,177,306`.
The invitation widget consumes these exact instruction keys:

| Key | Meaning supported in all three inspected locales |
| --- | --- |
| `download_the_glazok_2_app` | Download Glazok 2 onto the child's phone. |
| `enter_the_code` | Enter this code into Glazok 2 on the child's phone. |
| `you_must_give_permissions` | Grant permissions to Glazok 2 on the child's phone. |
| `android_only_notice` | The child-device part is supported only on Android phones. |
| `write_in_your_child` | Repeats where to enter the displayed code. |

References: `ru-RU.json:374–377,383`, `uz-UZ.json:375–378,386`,
`en-US.json:372–375,381`; consumer `child_code_widget.dart:23–28,361`.
The Android restriction is an archived product statement, not a verified current
MANA/iPhone support claim. Older generic strings elsewhere use Glazok without 2;
do not combine their branding into a new installation instruction.

The widget embeds three GIF assets as illustrations. The separate Instructions
tab embeds a YouTube player. Neither external video playback nor the GIF contents
were verified in this research. They cannot fill the missing child-side steps.

## Existing-child code and legacy alternatives

The active child-card route opens `ChildFeaturesScreen`
(`lib/screens/child/widgets/child_card.dart:79–87`). If its API model says the child
is not connected, `_initData` calls `getChildCode` (`child_features_screen.dart:312–321`).
That method calls `AuthService.shareChild(childId)`, an authenticated POST to
**`/api/v1/child/list/{childId}/share/`**, and uses its returned `token`
(`child_features_screen.dart:842–849`, `lib/services/api/auth.dart:326–343`).
The screen can show that code with the same `enter_the_code` text and an Invite
button that shares the configured child-download URL (`767–835`). It also observes
`childAdded` (`330–337`). This is a separate existing-profile path, not evidence
that a new profile must be created whenever a phone is offline. The display uses
additional connection-state logic (`668–689`); that implementation is not proof of
present connectivity or successful setup in a real family.

Legacy `ChildCardGeo` / `ChildCardGeoWithoutChild` contain the reverse direction:
an input for a code from the child's phone followed by
`AuthService.parentLogin(code)` (`lib/screens/child/child_card_geo.dart:615–682`,
`child_card_geo_without_child.dart:473–532`). The service POSTs `code` to
`/parent-login/` (`lib/services/api/auth.dart:346–369`). The inspected source has
no active constructor call sites for those two legacy screen classes. Likewise,
`InviteChildScreen` has no active call site found; its share content is a placeholder.
The edit screen's code-sharing actions are commented out. These remnants and
generic translation keys do not establish another current parent-app setup option.
Do not mix their reverse code direction into the traced invitation-code flow.

No separate **parent confirms the connection**, QR scan, SMS setup code, code
expiry/regeneration rule, reinstall/reset sequence, paid requirement or specific
child permission dialog is proven by the active trace. The parent archive also
contains an old `loginChild(code)` service method; that does not replace missing
source for the separate child application or establish its current endpoint.

## Recommendation for a typed agent guide

Add a small host-owned immutable setup guide as a separate typed value on **new**
setup-help admissions. Keep the source evidence in this document; do not send the
archive, raw Dart, API payloads, invitation-code values or external support contacts
to the model. Suggested fields are:

- guide ID, protocol, content hash, archive/file evidence hashes, research date
  and a separate release-validation date/status;
- exact parent product/flavor, platform, package ID, app version/build, plus the
  verified child product/package/version range and supported child platform;
- explicit applicability `unverified`, `archive_match` or `current_release_match`,
  selected by trusted application metadata plus a reviewed release mapping;
- locale and bounded typed step IDs with exact approved labels, actor/device,
  required/optional status and evidence references;
- explicit unknowns: child-side permission sequence, code lifetime/recovery,
  current MANA branding/store mapping and completion criteria where unverified.

An archive version match alone is not a current-release attestation. Do not use a
parent's language, product name, model guess, shared API ownership or source lineage
to assert that mapping. For the present evidence, applicability remains
**unverified for current MANA**. Archived details can answer an explicitly historical
question with that qualification; they must not become unqualified installed-app
instructions. A trusted backend can later provide the installed package/build,
while an app-owner-reviewed mapping supplies the compatible guide. Fail closed
on absent/conflicting metadata instead of choosing the nearest version.

When no guide matches, Parent-Touch can state that it lacks verified instructions
for that version and ask one exact device/current-screen clarification, for example:
“Which setup screen is open on the child's phone?” It must not invent a confirmation
step, permission name, store link or code direction. Do not ask parents to paste
pairing codes, credentials or private child data into chat. If an exact UI step
remains unknown, preserve the limit and direct the parent to support offered by
their installed app; do not publish an archived contact address as current support.

Freeze the selected guide/provenance and exact bound answer in the new private
capture. Existing family42 replies, old protocols, replays and unknown submitted
calls must not acquire it retroactively. A guide permits explanation only: it
grants no account/source/contact/linking write, installation, approval, Safety
assessment or payment authority. Keep the same owner/question chain, current
fences, ordinary Parent-Touch routing and unchanged 2000/2000 raw allowances.

Before claiming new dialogue quality, use fake checks for version mismatch,
missing child-side facts, code-direction consistency, replay/restart and no Safety
handoff for ordinary setup. Any separately authorized actual-model whole-dialogue
case must be a new party under the unchanged allowance. Preserve both earlier
negative setup parties and their costs; this source inspection does not turn them
into passes or establish a complete linking conversation.

## File fingerprints

SHA-256 hashes are over uncompressed archive-member bytes, without newline or
whitespace normalization. The archive hash binds additional referenced members.

| Archive-relative file | SHA-256 |
| --- | --- |
| `README.md` | `ce0494e7c78b9e8628edc2d70dd4ad3a6fb371d31e1f5514d3401e29a1677b1d` |
| `pubspec.yaml` | `2aeba23a112ddd37fba13159a7171c2d2d24be43f2998a87d78c9a1341b45662` |
| `lib/main.dart` | `7e7cabab8b3d964df9ca3641257d75793572831acf0c1beeb54923117908369f` |
| `lib/bosstracker_app.dart` | `2db12b7e92bf509f8d1e9a93b9259cc6265c702b864c6587816b86e2cd93f618` |
| `lib/common/constants.dart` | `0363172a5544356aa11f9f6ec03ee656342561ec9042d6e1b0fb6418325475f6` |
| `android/app/build.gradle.kts` | `a9f6b8294e695bfa62feaed9ad29914b1a1492a50e0284c00f62329d6abb4924` |
| `android/app/src/main/AndroidManifest.xml` | `023ae75f8f01cc65d36369578466ff1b9a8e74ac7fd0ff1dc6c0beb5e817ee33` |
| `ios/Runner/Info.plist` | `dea77e62931df1fd0f6611365137c97b433acf2960aa4416d475c35b085c05d3` |
| `ios/Runner.xcodeproj/project.pbxproj` | `09617750ca7c9a3f12a70d6e5a1eeb5c43a183b5a5a1cc3d9be58eef1b0af44a` |
| `lib/src/features/child/presentation/screens/main_page.dart` | `8b5ce71506a0d68af7b8fc6794b786e6190ac368afbea1b994c8cacfda64d76d` |
| `lib/src/features/child/presentation/screens/home_page.dart` | `d0a8aee520586f4b214c75401df1fe1a2a2739f3cd40f29c9e8dcd8dc410eaa3` |
| `lib/src/features/child/presentation/widgets/w_children_widget.dart` | `b1d47f8940b416201bc3a317bc50e7b12e7b50d8530ca81fff32c8fafd8a9e09` |
| `lib/src/features/child/presentation/screens/initial_child_screen.dart` | `122502670c38f334799cd998e9e84b7d0f5b987918bfc451ffa928431a669f76` |
| `lib/src/features/child/presentation/screens/add_child_screen.dart` | `5668fbba41c805d9eecc28d504bf3af61dde98ae2ab345dee64067d649a21af2` |
| `lib/src/features/child/presentation/widgets/child_name_screen.dart` | `27c3f4cb170fd71c10109a24950a54f0b5b25fafaeabf017f8dfb11dc9ce5b18` |
| `lib/src/features/child/presentation/widgets/add_child_image.dart` | `61e00f5a7b325e24b5a5b7c7f1bcf54515e91410d38d88e8a404119559207583` |
| `lib/src/features/child/presentation/widgets/uploaded_image.dart` | `4a930c276a7f91cdfbc11bb2b870c5d73b4e51da4d611d5cd8f69d7db5e205b8` |
| `lib/src/features/child/presentation/widgets/child_code_widget.dart` | `cdebce7ed161e2699b0d92e803a77531637c1e52bac68a05909258ef13ccd740` |
| `lib/src/features/child/presentation/bloc/child_bloc.dart` | `ae65769c075af5476d4ba6733c572e6ab6c5b4f591a186fb2121f393733188e3` |
| `lib/src/features/child/domain/use_case/add_child_use_case.dart` | `a2af09915b6cd6d7c3213b66654d2f032ff69a65e842df1bcd76aa78a741ae3b` |
| `lib/src/features/child/data/Repository/repository_implementation.dart` | `f9874ffd153b1902c63c84ec82f24595af2275ad36e983649f10713a59eb5787` |
| `lib/src/features/child/data/Data/remote/child_data_source.dart` | `8a9f39fbb7d6af0074b860ce34ce6456b81446c3eca64464ea46aeb394179148` |
| `lib/src/constants/request_path.dart` | `4ddf60e91692990e6bca3cc7acda36e511592725d2e2c98beb895d1988fdb9ee` |
| `lib/src/features/child/presentation/screens/child_features_screen.dart` | `3aafe6741a9a9bc1d48caa19371f1a71376329f4a7c89b88cd419e89f3d17bdf` |
| `lib/services/api/auth.dart` | `00bae5eb9760640bc4bcf01154264b701bc1617374f82bbc8ca95f943ba9c549` |
| `assets/langs/ru-RU.json` | `a55ff5fb045cc297e9bccfbd957724ec1cb4815edded419dd7c161261b198867` |
| `assets/langs/uz-UZ.json` | `8df4621dcc01e06833d4c38b061db37d20ad6bfdd8bbf33c900cf78202d60e05` |
| `assets/langs/en-US.json` | `42bf4dbb84a2d3650dad9f8beb19ec8c0c5dab2aa7711594f41b71010c761dbe` |

The ZIP was read without extraction. Member hashes, targeted line references,
locale-key values and active/legacy call sites were inspected locally. No Flutter
build, app execution, backend acceptance, current store verification, paid test or
repository-wide verification is claimed for this documentation-only research.
