/* Shared dataset + types for the bake-off. Frame-agnostic (plain TS). */

export type Bucket = "act" | "rev" | "blk" | "res";
export interface Leg { side: "YES" | "NO"; label: string; px: string; sz: number; }
export interface Conf { [k: string]: number; }
export interface Row {
  id: string;
  bucket: Bucket;
  chg: "" | "new" | "up" | "down" | "ret";
  sport: string;
  name: string;
  sub: string;
  setup: string;
  edge: number;
  roi: number;
  units: number;
  profit: number;
  tradable: string;
  cav: string;
  sev: "" | "adv" | "rev" | "blk" | "res";
  quote: string;
  touch: number;
  cost: number;
  floor: number;
  worst: number;
  best: number;
  be: number;
  fill: number;
  legs: Leg[];
  conf: Conf;
  spark: number[];
}

/* api.Opportunity subset (api.py:54) — kept in sync; extra fields ignored. */
export interface ApiOpportunity {
  opportunity_id?: string; sport_label?: string; name?: string; detail?: string;
  setup_type?: string; relationship_type?: string;
  exec_gap_c?: number; roi_pct?: number; exec_min_size?: number; exec_max_profit_dollars?: number;
  cost_c?: number; payout_floor_c?: number; worst_case_profit_c?: number; best_case_profit_c?: number;
  tradable_now?: string; settlement_caveat?: string; bucket?: string;
  action_1_text?: string; action_2_text?: string; action_1_price_c?: number; action_2_price_c?: number;
  legs?: any[];
}

const CONF = (d:number,q:number,l:number,e:number,s:number,st:number,m:number,c:number,x:number):Conf =>
  ({Data:d,Quote:q,Liquidity:l,Execution:e,Settlement:s,Strategy:st,Model:m,Comparability:c,Complexity:x});

export const SEED: Row[] = [
 {id:"1",bucket:"act",chg:"new",sport:"Tennis",name:"J. Sinner",sub:"Reach Final ⊇ Win",setup:"Containment",edge:7,roi:14.0,units:140,profit:9.80,tradable:"Yes",cav:"—",sev:"",quote:"Tight",touch:38,cost:93,floor:100,worst:-7,best:7,be:93,fill:140,legs:[{side:"YES",label:"Reach Final · KXATPADVANCE",px:"38¢",sz:140},{side:"NO",label:"Win · KXFOMEN",px:"55¢",sz:140}],conf:CONF(95,92,78,80,88,96,60,84,90),spark:[34,35,33,36,38,37,38]},
 {id:"2",bucket:"act",chg:"up",sport:"Soccer",name:"Brazil v Serbia",sub:"Home/Away/Tie 3-way",setup:"Dutch overround",edge:11,roi:5.5,units:90,profit:9.90,tradable:"Yes",cav:"Game postpone",sev:"adv",quote:"OK",touch:61,cost:211,floor:200,worst:-11,best:11,be:106,fill:90,legs:[{side:"NO",label:"Home · KXWCGAME",px:"61¢",sz:90},{side:"NO",label:"Away · KXWCGAME",px:"78¢",sz:90},{side:"NO",label:"Tie · KXWCGAME",px:"72¢",sz:90}],conf:CONF(94,80,70,74,82,95,55,80,78),spark:[5,6,8,7,9,10,11]},
 {id:"3",bucket:"act",chg:"",sport:"NHL",name:"Oilers @ Panthers",sub:"Head-to-head game",setup:"Game dutch",edge:4,roi:4.0,units:200,profit:8.00,tradable:"Yes",cav:"—",sev:"",quote:"Tight",touch:47,cost:96,floor:100,worst:-4,best:4,be:96,fill:200,legs:[{side:"YES",label:"Oilers · KXNHLGAME",px:"47¢",sz:200},{side:"YES",label:"Panthers · KXNHLGAME",px:"49¢",sz:200}],conf:CONF(96,94,88,86,90,96,62,85,92),spark:[2,3,3,4,4,3,4]},
 {id:"4",bucket:"act",chg:"ret",sport:"Esports",name:"FaZe v Vitality",sub:"Map-1 draw-free",setup:"Map dutch",edge:3,roi:3.0,units:60,profit:1.80,tradable:"Yes",cav:"—",sev:"",quote:"OK",touch:52,cost:97,floor:100,worst:-3,best:3,be:97,fill:60,legs:[{side:"YES",label:"FaZe · KXCS2MAP",px:"52¢",sz:60},{side:"YES",label:"Vitality · KXCS2MAP",px:"45¢",sz:60}],conf:CONF(90,78,60,66,86,94,50,70,88),spark:[3,2,0,1,2,3,3]},
 {id:"5",bucket:"rev",chg:"new",sport:"NBA",name:"Boston Celtics",sub:"Reach SF ≡ Win Conf",setup:"Equivalence",edge:4,roi:6.0,units:50,profit:2.00,tradable:"Rule-dependent",cav:"RULE_CHECK_REQ",sev:"rev",quote:"OK",touch:71,cost:104,floor:100,worst:-4,best:4,be:104,fill:50,legs:[{side:"YES",label:"Reach SF · KXNBA",px:"71¢",sz:50},{side:"NO",label:"Win Conf · KXNBA",px:"33¢",sz:50}],conf:CONF(88,76,64,60,55,80,48,72,70),spark:[1,2,3,3,4,4,4]},
 {id:"6",bucket:"rev",chg:"",sport:"Tennis",name:"C. Alcaraz",sub:"Score bundle ≡ Win",setup:"Synthetic",edge:5,roi:5.0,units:40,profit:2.00,tradable:"Review rules",cav:"SETTLE_CHECK_REQ",sev:"rev",quote:"Wide",touch:54,cost:95,floor:100,worst:-5,best:5,be:95,fill:40,legs:[{side:"YES",label:"3-0 · KXATPEXACT",px:"12¢",sz:40},{side:"YES",label:"3-1",px:"18¢",sz:40},{side:"YES",label:"3-2",px:"21¢",sz:40},{side:"NO",label:"Match winner",px:"54¢",sz:40}],conf:CONF(84,58,50,48,45,78,42,60,55),spark:[4,5,5,4,5,5,5]},
 {id:"7",bucket:"blk",chg:"",sport:"MLB",name:"LA Dodgers",sub:"Playoffs ⊇ Win WS",setup:"Containment",edge:6,roi:0,units:0,profit:0,tradable:"No",cav:"Blocked: no size",sev:"blk",quote:"One-sided",touch:60,cost:0,floor:100,worst:0,best:0,be:0,fill:0,legs:[{side:"YES",label:"Reach Playoffs · KXMLB",px:"—",sz:0},{side:"NO",label:"Win WS · KXMLB",px:"—",sz:0}],conf:CONF(80,30,10,15,78,82,40,55,75),spark:[6,6,5,6,6,6,6]},
 {id:"8",bucket:"res",chg:"",sport:"Tennis",name:"Alcaraz vs Sinner",sub:"Pairs divergence z=−2.3",setup:"Research signal",edge:0,roi:0,units:0,profit:0,tradable:"Research",cav:"not a trade",sev:"res",quote:"—",touch:0,cost:0,floor:0,worst:0,best:0,be:0,fill:0,legs:[],conf:CONF(70,50,55,0,0,40,62,58,50),spark:[0,-1,-1,-2,-2,-2,-2]},
];

const SPORTS = ["Tennis","Soccer","NHL","Esports","NBA","MLB","Golf","NFL","WNBA","Motorsport"];

/** Expand the seed to n rows (for stress testing). Deterministic per index. */
export function genRows(n: number): Row[] {
  const out: Row[] = [];
  for (let i = 0; i < n; i++) {
    const base = SEED[i % SEED.length];
    const j = (i * 2654435761) % 97;            // deterministic jitter, no Math.random
    const edge = Math.max(0, base.edge + (j % 13) - 6);
    out.push({
      ...base,
      id: "r" + i,
      sport: SPORTS[i % SPORTS.length],
      name: base.name + (i >= SEED.length ? " #" + i : ""),
      edge,
      roi: base.roi ? +(base.roi + (j % 7) - 3).toFixed(1) : 0,
      touch: base.touch ? Math.min(95, Math.max(5, base.touch + (j % 11) - 5)) : 0,
      spark: base.spark.slice(),
      conf: { ...base.conf },
      legs: base.legs.map(l => ({ ...l })),
    });
  }
  return out;
}

export function mapApi(o: ApiOpportunity): Row {
  const bucket = (o.bucket === "actionable" ? "act" : o.bucket === "review" ? "rev" : o.bucket === "blocked" ? "blk" : "act") as Bucket;
  return {
    id: o.opportunity_id || Math.random().toString(36).slice(2),
    bucket, chg: "", sport: o.sport_label || "", name: o.name || "", sub: o.detail || "",
    setup: o.setup_type || o.relationship_type || "", edge: o.exec_gap_c ?? 0, roi: o.roi_pct ?? 0,
    units: o.exec_min_size ?? 0, profit: o.exec_max_profit_dollars ?? 0, tradable: o.tradable_now || "",
    cav: o.settlement_caveat || "—", sev: "", quote: "", touch: Math.round(o.action_1_price_c ?? 0),
    cost: o.cost_c ?? 0, floor: o.payout_floor_c ?? 100, worst: o.worst_case_profit_c ?? 0, best: o.best_case_profit_c ?? 0,
    be: 0, fill: o.exec_min_size ?? 0,
    legs: (o.legs || []).map((l:any)=>({side:(l.side||"YES"),label:l.label||l.ticker||"",px:l.price||l.px||"",sz:l.size||0})),
    conf: SEED[0].conf, spark: [0,0,0,0,0,0,0],
  };
}

export async function loadReal(): Promise<Row[]> {
  const res = await fetch("/api/opportunities");
  if (!res.ok) throw new Error("api " + res.status);
  const data = (await res.json()) as ApiOpportunity[];
  return data.map(mapApi);
}
