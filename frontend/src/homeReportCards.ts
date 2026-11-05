export const REPORT_CARDS={
 attention:{section:'todo',title:'週報待追蹤',description:'已退回、請款、應收與儀器送修',tab:'review'},
 qualityTrend:{section:'quality',title:'外業失誤率 · 12 週',description:'已退回占已檢核的比例與趨勢',tab:'review'},
 qualityGroups:{section:'quality',title:'各組失誤率',description:'依已檢核樣本比較各組',tab:'review'},
 funnel:{section:'business',title:'合約 → 請款 → 入帳',description:'合約、請款與入帳金額',tab:'sales'},
 receivables:{section:'business',title:'應收未收前 5 案',description:'依應收未收金額排序',tab:'sales'},
 achievement:{section:'progress',title:'預排達成率',description:'報告週實際與預排比較',tab:'progress'},
 instruments:{section:'resources',title:'儀器',description:'儀器使用、閒置與送修',tab:'assets'},
 vehicles:{section:'resources',title:'車輛',description:'車輛使用與閒置',tab:'assets'},
} as const;
export type ReportCardId=keyof typeof REPORT_CARDS;
export const isReportCard=(id:string):id is ReportCardId=>Object.hasOwn(REPORT_CARDS,id);
export const reportHref=(tab:typeof REPORT_CARDS[ReportCardId]['tab'])=>'#view=reports&tab='+tab;
export const canReadHomeReports=(role:string|undefined|null)=>role==='pm'||role==='manager';
