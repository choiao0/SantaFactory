package com.ssafy.santafactory.repository;

import com.ssafy.santafactory.entity.store.Product;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;

import java.util.List;

public interface ProductRepository extends JpaRepository<Product, Long> {

    /**
     * 출고 주문 생성 대상 상품 마스터 전부 — store·rack 을 같이 읽어 N+1 을 막는다.
     *
     * <p>창고별로 필터링하지 않는다. 물리 레이아웃(zone·store·rack·product)은 애초에 창고마다
     * 따로 있는 게 아니라 앱 전체에 하나뿐인 고정 마스터데이터다({@code WarehouseService}는 창고
     * 생성 시 zone·product 를 전혀 만들지 않는다) — 파이썬 워커도 요청의 warehouse_id 와 무관하게
     * 같은 마스터 파일을 항상 썼다.
     */
    @Query("SELECT p FROM Product p JOIN FETCH p.store JOIN FETCH p.rack")
    List<Product> findAllWithStoreAndRack();
}
