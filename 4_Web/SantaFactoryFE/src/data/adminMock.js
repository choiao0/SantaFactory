// 관리자 대시보드 목업 — 회원=창고=견적 1:1:1 가정. 나중에 API 응답으로 교체.
// status 값은 실제 EstimateStatus(RUNNING/DONE/PARTIAL/CANCELLED)와 맞춤.
export const MOCK_ADMIN_ESTIMATES = [
  { id: 1, userName: 'kim01', warehouseName: '품고 A', estimateId: 16, status: 'DONE', recommendedCount: 6 },
  { id: 2, userName: 'lee02', warehouseName: '품고 B', estimateId: 9, status: 'RUNNING', recommendedCount: null },
  { id: 3, userName: 'park03', warehouseName: '품고 C', estimateId: 14, status: 'PARTIAL', recommendedCount: null },
  { id: 4, userName: 'choi04', warehouseName: '품고 D', estimateId: 11, status: 'DONE', recommendedCount: 6 },
  { id: 5, userName: 'jung05', warehouseName: '품고 E', estimateId: 13, status: 'DONE', recommendedCount: 6 },
  { id: 6, userName: 'yoon06', warehouseName: '품고 F', estimateId: 20, status: 'CANCELLED', recommendedCount: null },
]
