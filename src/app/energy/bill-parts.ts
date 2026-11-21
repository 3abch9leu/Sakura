import { BillLang } from '../api';

/**
 * Plain-language meaning of every part of a STEG electricity bill, in 4 languages.
 * Facts come from the official STEG tariff and "Comprendre votre facture" pages (see data/steg_tariff.json).
 */
export type PartId =
  | 'period' | 'power' | 'reading' | 'index_previous' | 'index_current' | 'consumption'
  | 'energy' | 'fixed' | 'taxes' | 'electricity_total' | 'total';

export interface PartDef {
  id: PartId;
  /** bill field(s) holding the value; the first one carries the box on the image */
  keys: string[];
  unit?: string;
  kind: 'number' | 'date' | 'reading';
  /** needed to check the bill (otherwise optional) */
  essential?: boolean;
  name: Record<BillLang, string>;
  meaning: Record<BillLang, string>;
}

export const PARTS: PartDef[] = [
  {
    id: 'period', keys: ['period_start', 'period_end'], kind: 'date',
    name: { en: 'Billing period', fr: 'Période de facturation', ar: 'فترة الفوترة', darija: 'فترة الفاتورة' },
    meaning: {
      en: 'The days this bill covers. STEG usually bills every 2 months.',
      fr: 'Les jours couverts par cette facture. La STEG facture en général tous les 2 mois.',
      ar: 'الأيام التي تغطيها هذه الفاتورة. تفوتر الستاغ عادةً كل شهرين.',
      darija: 'النهارات اللي تحسبهم الفاتورة هاذي. الستاغ عادة تفوتر كل شهرين.',
    },
  },
  {
    id: 'power', keys: ['subscribed_power_kva'], unit: 'kVA', kind: 'number', essential: true,
    name: { en: 'Subscribed power', fr: 'Puissance souscrite', ar: 'القدرة المكتتبة', darija: 'القدرة' },
    meaning: {
      en: 'The maximum power your meter allows. It sets your fixed fee (0.700 TND per kVA per month). With 1 or 2 kVA you can get the two cheapest price bands.',
      fr: 'La puissance maximale de votre compteur. Elle fixe la redevance (0,700 DT par kVA et par mois). À 1 ou 2 kVA, vous avez accès aux deux tranches les moins chères.',
      ar: 'أقصى قدرة يسمح بها عدّادك. تحدد معلوم القدرة (0,700 دينار لكل كيلوفولت أمبير شهريًا). بـ1 أو 2 كيلوفولت أمبير تستفيد من أرخص شريحتين.',
      darija: 'أقصى قوة يعطيها الكونتور متاعك. عليها يتحسب معلوم القدرة (0,700 دينار للـkVA في الشهر). كان عندك 1 ولا 2 kVA تنجم تاخو أرخص زوز شرائح.',
    },
  },
  {
    id: 'reading', keys: ['reading_type'], kind: 'reading',
    name: { en: 'Reading type', fr: 'Type de relevé', ar: 'نوع القراءة', darija: 'نوع القراية' },
    meaning: {
      en: 'ACTUAL: an agent read your meter. ESTIMATED: STEG guessed from your last 24 months, and it is corrected at the next actual reading.',
      fr: 'RÉEL : un agent a lu votre compteur. ESTIMÉ : la STEG a estimé à partir de vos 24 derniers mois ; c\'est corrigé au prochain relevé réel.',
      ar: 'حقيقية: عون قرأ عدّادك. تقديرية: قدّرت الستاغ استهلاكك حسب آخر 24 شهرًا، ويُصحَّح ذلك في القراءة الحقيقية القادمة.',
      darija: 'حقيقية: عون جا وقرا الكونتور. تقديرية: الستاغ قدّرت على حساب آخر 24 شهر، وتتصلّح في القراية الجاية.',
    },
  },
  {
    id: 'index_previous', keys: ['index_previous'], kind: 'number',
    name: { en: 'Old meter index', fr: 'Ancien index', ar: 'المؤشر القديم', darija: 'المؤشر القديم' },
    meaning: {
      en: 'The number on your meter at the start of the period.',
      fr: 'Le chiffre de votre compteur au début de la période.',
      ar: 'الرقم الذي كان على عدّادك في بداية الفترة.',
      darija: 'النومرو اللي كان في الكونتور في أول الفترة.',
    },
  },
  {
    id: 'index_current', keys: ['index_current'], kind: 'number',
    name: { en: 'New meter index', fr: 'Nouvel index', ar: 'المؤشر الجديد', darija: 'المؤشر الجديد' },
    meaning: {
      en: 'The number on your meter at the end of the period. You can compare it with your own meter.',
      fr: 'Le chiffre du compteur à la fin de la période. Vous pouvez le comparer avec votre compteur.',
      ar: 'الرقم على العدّاد في نهاية الفترة. يمكنك مقارنته بنفسك مع عدّادك.',
      darija: 'النومرو في الكونتور في آخر الفترة. تنجم تقارنو بروحك مع الكونتور.',
    },
  },
  {
    id: 'consumption', keys: ['consumption_kwh'], unit: 'kWh', kind: 'number', essential: true,
    name: { en: 'Consumption', fr: 'Consommation', ar: 'الاستهلاك', darija: 'الاستهلاك' },
    meaning: {
      en: 'The electricity you used: new index minus old index. This is the number that decides your bill.',
      fr: 'L\'électricité utilisée : nouvel index moins ancien index. C\'est le chiffre qui décide de votre facture.',
      ar: 'الكهرباء التي استعملتها: المؤشر الجديد ناقص القديم. هذا الرقم هو الذي يحدد مبلغ فاتورتك.',
      darija: 'قدّاش استعملت ضو: المؤشر الجديد ناقص القديم. هاذا هو الرقم اللي يقرر الفاتورة.',
    },
  },
  {
    id: 'energy', keys: ['energy_amount_tnd'], unit: 'TND', kind: 'number',
    name: { en: 'Energy amount', fr: 'Montant consommation', ar: 'مبلغ الاستهلاك', darija: 'مبلغ الاستهلاك' },
    meaning: {
      en: 'Consumption × price per kWh, before taxes. The price depends on how much you use per month: all your kWh get the price of your band.',
      fr: 'Consommation × prix du kWh, hors taxes. Le prix dépend de votre consommation mensuelle : tous vos kWh sont au prix de votre tranche.',
      ar: 'الاستهلاك × سعر الكيلوواط ساعة، دون أداءات. السعر يتبع استهلاكك الشهري: كل الكيلوواطات تُحتسب بسعر شريحتك.',
      darija: 'الاستهلاك × سوم الكيلوواط، بلا أداءات. السوم حسب قدّاش تستهلك في الشهر: الكيلوواطات الكل يتحسبو بسوم الشريحة متاعك.',
    },
  },
  {
    id: 'fixed', keys: ['fixed_charges_tnd'], unit: 'TND', kind: 'number',
    name: { en: 'Fixed charges', fr: 'Frais fixes (redevance)', ar: 'المعاليم القارة', darija: 'المعاليم القارة' },
    meaning: {
      en: 'The power fee you pay even if you use nothing: kVA × 0.700 TND × months.',
      fr: 'La redevance de puissance, due même sans consommation : kVA × 0,700 DT × mois.',
      ar: 'معلوم القدرة الذي تدفعه حتى دون استهلاك: الكيلوفولت أمبير × 0,700 دينار × عدد الأشهر.',
      darija: 'معلوم القدرة اللي تخلصو حتى كان ما استهلكتش: kVA × 0,700 دينار × الشهورات.',
    },
  },
  {
    id: 'taxes', keys: ['taxes_tnd'], unit: 'TND', kind: 'number',
    name: { en: 'Taxes', fr: 'Taxes', ar: 'الأداءات', darija: 'الأداءات' },
    meaning: {
      en: 'VAT (7 % up to 300 kWh/month, otherwise 13 %), plus 5 millimes per kWh for local authorities and 5 millimes per kWh for the energy transition fund (FTE).',
      fr: 'TVA (7 % jusqu\'à 300 kWh/mois, sinon 13 %), plus 5 millimes par kWh pour les collectivités locales et 5 millimes par kWh pour le Fonds de transition énergétique (FTE).',
      ar: 'الأداء على القيمة المضافة (7٪ حتى 300 كيلوواط ساعة شهريًا وإلا 13٪)، زائد 5 مليمات لكل كيلوواط ساعة للجماعات المحلية و5 مليمات لصندوق الانتقال الطاقي.',
      darija: 'الـTVA (7٪ حتى 300 كيلوواط في الشهر، وإلا 13٪)، زيد 5 مليم للبلدية و5 مليم لصندوق الانتقال الطاقي على كل كيلوواط.',
    },
  },
  {
    id: 'electricity_total', keys: ['electricity_total_tnd'], unit: 'TND', kind: 'number',
    name: { en: 'Electricity total', fr: 'Total électricité', ar: 'مجموع الكهرباء', darija: 'مجموع الضو' },
    meaning: {
      en: 'Energy + fixed charges + taxes. This is the part we check against the official STEG tariff.',
      fr: 'Consommation + frais fixes + taxes. C\'est la partie que nous vérifions avec le tarif officiel de la STEG.',
      ar: 'الاستهلاك + المعاليم القارة + الأداءات. هذا الجزء الذي نتحقق منه بالتعريفة الرسمية للستاغ.',
      darija: 'الاستهلاك + المعاليم القارة + الأداءات. هاذا الجزء اللي نثبتو فيه بالتعريفة الرسمية متاع الستاغ.',
    },
  },
  {
    id: 'total', keys: ['total_tnd'], unit: 'TND', kind: 'number',
    name: { en: 'Amount to pay', fr: 'Net à payer', ar: 'المبلغ الصافي للدفع', darija: 'المبلغ اللي تخلصو' },
    meaning: {
      en: 'Everything on the bill: electricity, and sometimes gas, the RTT (radio-TV) contribution or unpaid amounts.',
      fr: 'Tout ce qui est sur la facture : l\'électricité, et parfois le gaz, la contribution RTT ou des impayés.',
      ar: 'كل ما في الفاتورة: الكهرباء، وأحيانًا الغاز ومساهمة RTT أو مبالغ غير مدفوعة.',
      darija: 'كل شي في الفاتورة: الضو، وساعات الغاز، مساهمة RTT ولا فلوس قدم ما تخلصتش.',
    },
  },
];

/** Interface text that changes with the explanation language. */
export const UI: Record<BillLang, Record<string, string>> = {
  en: {
    explainedTitle: 'Your bill, part by part',
    noTyping: 'You don\'t need to type anything. We read these values from your bill. Tap a part to see what it means, check the values, then press "Check my bill".',
    manualIntro: 'Type the values from your bill. Only the consumption and the subscribed power are needed; every extra value lets us check more.',
    read: 'Read', check: 'Please check', edit: 'Correct', done: 'Done', missing: 'Not found on your bill',
    missingHint: 'Optional: add them if you can see them on your bill.', add: 'Add',
    actual: 'Actual', estimated: 'Estimated', choose: 'Choose one',
  },
  fr: {
    explainedTitle: 'Votre facture, partie par partie',
    noTyping: 'Vous n\'avez rien à taper. Nous avons lu ces valeurs sur votre facture. Touchez une partie pour voir ce qu\'elle veut dire, vérifiez les valeurs, puis appuyez sur « Vérifier ma facture ».',
    manualIntro: 'Tapez les valeurs de votre facture. Seules la consommation et la puissance souscrite sont nécessaires ; chaque valeur en plus permet de vérifier davantage.',
    read: 'Lu', check: 'À vérifier', edit: 'Corriger', done: 'OK', missing: 'Non trouvé sur votre facture',
    missingHint: 'Facultatif : ajoutez-les si vous les voyez sur votre facture.', add: 'Ajouter',
    actual: 'Réel', estimated: 'Estimé', choose: 'Choisissez',
  },
  ar: {
    explainedTitle: 'فاتورتك جزءًا بجزء',
    noTyping: 'لا حاجة لكتابة أي شيء. قرأنا هذه القيم من فاتورتك. اضغط على أي جزء لترى معناه، تحقّق من القيم، ثم اضغط «تحقّق من فاتورتي».',
    manualIntro: 'اكتب القيم من فاتورتك. نحتاج فقط الاستهلاك والقدرة المكتتبة؛ وكل قيمة إضافية تسمح بتحقق أكثر.',
    read: 'مقروء', check: 'يرجى التثبت', edit: 'تصحيح', done: 'تم', missing: 'غير موجود في فاتورتك',
    missingHint: 'اختياري: أضفها إن كانت ظاهرة في فاتورتك.', add: 'إضافة',
    actual: 'حقيقية', estimated: 'تقديرية', choose: 'اختر',
  },
  darija: {
    explainedTitle: 'الفاتورة متاعك جزء بجزء',
    noTyping: 'ما تكتب حتى شي. قرينا الأرقام هاذي من الفاتورة متاعك. انزل على أي جزء باش تفهم شنوة معناه، ثبّت في الأرقام، ومبعد انزل على «ثبّت في الفاتورة».',
    manualIntro: 'اكتب الأرقام من الفاتورة متاعك. نستحقو كان الاستهلاك والقدرة؛ وكل رقم زايد يخلينا نثبتو أكثر.',
    read: 'تقرا', check: 'ثبّت فيه', edit: 'صلّح', done: 'باهي', missing: 'ما لقيناهش في الفاتورة',
    missingHint: 'موش لازم: زيدهم كان تشوفهم في الفاتورة.', add: 'زيد',
    actual: 'حقيقية', estimated: 'تقديرية', choose: 'اختار',
  },
};
